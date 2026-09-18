import zipfile
from io import BytesIO

import pytest
import requests

from app.fetch.platform_adapters import (
    LockedError,
    UnreachableError,
    UnsupportedPlatformError,
    classify_platform,
    resolve_package,
)

COSINEX_OPEN_HTML = """<html><body>
<a href="./documents/archive/Vergabeunterlagen_CXTEST.zip;jsessionid=abc">Alle Dokumente</a>
</body></html>"""

COSINEX_LOCKED_HTML = """<html><body>
Um Zugriff auf dieses Modul zu erhalten m\u00fcssen Sie am Vergabeverfahren teilnehmen.
Jetzt teilnehmen
</body></html>"""

RIB_LISTING_HTML = (
    '<html><body>'
    '<a href=\\"https:\\/\\/my.example.de\\/remote\\/download.php?k=key1\\">eForm_16.pdf<\\/a>'
    '<a href=\\"https:\\/\\/my.example.de\\/remote\\/download.php?k=key2\\">Tender Documents of Sep 3, 2026 (PDF) <\\/a>'
    '</body></html>'
)


class _FakeResponse:
    def __init__(self, status_code=200, text="", content=b"", url="", headers=None):
        self.status_code = status_code
        self.text = text
        self.content = content or text.encode("utf-8")
        self.url = url
        self.headers = headers or {}


def _make_zip_bytes() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("a.pdf", b"pdf-bytes")
    return buffer.getvalue()


def test_classify_platform():
    assert classify_platform("https://s2.dtvp.de/Satellite/notice/CXABC/documents") == "cosinex_satellite"
    assert classify_platform("https://x.example.de/VMPSatellite/notice/CXABC/documents") == "cosinex_satellite"
    assert classify_platform("https://www.meinauftrag.rib.de/public/DetailsByPlatformIdAndTenderId/x/1") == "rib_meinauftrag"
    assert classify_platform("https://www.evergabe.de/auftraege/x/1") == "unsupported"


def test_resolve_package_cosinex_open(monkeypatch):
    zip_bytes = _make_zip_bytes()

    def fake_get(self, url, timeout=None, allow_redirects=None):
        if url.endswith("/documents"):
            return _FakeResponse(200, text=COSINEX_OPEN_HTML, url="https://x.example.de/VMPSatellite/public/company/project/CXTEST/de/documents?0")
        if "archive/Vergabeunterlagen_CXTEST.zip" in url:
            return _FakeResponse(200, content=zip_bytes)
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(requests.Session, "get", fake_get)
    result = resolve_package("https://x.example.de/VMPSatellite/notice/CXTEST/documents")
    assert result == zip_bytes


def test_resolve_package_cosinex_locked(monkeypatch):
    def fake_get(self, url, timeout=None, allow_redirects=None):
        return _FakeResponse(200, text=COSINEX_LOCKED_HTML, url="https://x.example.de/Satellite/public/company/project/CXTEST/de/overview?1")

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with pytest.raises(LockedError):
        resolve_package("https://x.example.de/Satellite/notice/CXTEST/documents")


def test_resolve_package_cosinex_unreachable_on_non_200(monkeypatch):
    def fake_get(self, url, timeout=None, allow_redirects=None):
        return _FakeResponse(500, text="", url=url)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with pytest.raises(UnreachableError):
        resolve_package("https://x.example.de/Satellite/notice/CXTEST/documents")


def test_resolve_package_cosinex_unreachable_on_timeout(monkeypatch):
    def boom(self, url, timeout=None, allow_redirects=None):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(requests.Session, "get", boom)
    with pytest.raises(UnreachableError):
        resolve_package("https://x.example.de/Satellite/notice/CXTEST/documents")


def test_resolve_package_rib_downloads_every_linked_document(monkeypatch):
    calls = []

    def fake_get(self, url, timeout=None, allow_redirects=None):
        calls.append(url)
        if "DetailsByPlatformIdAndTenderId" in url:
            return _FakeResponse(200, text=RIB_LISTING_HTML, url="https://www.meinauftrag.rib.de/public/publications/123")
        if "download.php?k=key1" in url:
            return _FakeResponse(200, content=b"pdf-one", headers={"Content-Type": "application/pdf"})
        if "download.php?k=key2" in url:
            return _FakeResponse(200, content=b"pdf-two", headers={"Content-Type": "application/pdf"})
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(requests.Session, "get", fake_get)
    result = resolve_package(
        "https://www.meinauftrag.rib.de/public/DetailsByPlatformIdAndTenderId/platformId/1/tenderId/1"
    )
    z = zipfile.ZipFile(BytesIO(result))
    names = z.namelist()
    assert len(names) == 2
    assert any(n.endswith(".pdf") for n in names)  # title without ".pdf" gets one appended
    assert z.read("eForm_16.pdf") == b"pdf-one"


def test_resolve_package_rib_unreachable_when_no_links(monkeypatch):
    def fake_get(self, url, timeout=None, allow_redirects=None):
        return _FakeResponse(200, text="<html>nothing here</html>", url=url)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    with pytest.raises(UnreachableError):
        resolve_package("https://www.meinauftrag.rib.de/public/DetailsByPlatformIdAndTenderId/platformId/1/tenderId/1")


def test_resolve_package_unsupported_platform_never_calls_requests(monkeypatch):
    def boom(self, *a, **k):
        raise AssertionError("should never call requests for an unsupported platform")

    monkeypatch.setattr(requests.Session, "get", boom)
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        resolve_package("https://www.evergabe.de/auftraege/suche-ueber-vergabestellen/x/1")
    assert exc_info.value.host == "www.evergabe.de"
