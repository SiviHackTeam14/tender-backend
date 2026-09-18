"""Platform hops: OCDS document URL -> downloadable package bytes (Story 1.2).

An OCDS ``tender.documents[].url`` is a platform *page*, never a file. Verified
live against real notices from ``data/raw_notices.json``:

- The "cosinex" e-procurement engine (``(VMP)?Satellite/notice/{token}``, used by
  ``dtvp.de``, ``evergabe.nrw.de``, and dozens of regional installs) resolves,
  via a normal session redirect, either to a ``.../documents`` page carrying a
  public ``archive/*.zip`` link (open procedures) or a ``.../overview`` page that
  says registration is required to unlock the documents module (restricted /
  two-stage procedures). Both are handled by ``fetch_cosinex_satellite``.
- The RIB "mein Auftrag" engine (``meinauftrag.rib.de`` and white-labelled
  installs) resolves to a public listing page embedding one
  ``downloadFile('.../remote/download.php?k=...')`` call per document, each
  anonymously downloadable. Handled by ``fetch_rib_meinauftrag``.
- Every other platform family is out of scope for this story (see the spec's
  Design Notes for the volumes and why) and is reported as ``unsupported``.
"""
from __future__ import annotations

import io
import re
import zipfile
from urllib.parse import urljoin, urlparse

import requests

# ── Classification ───────────────────────────────────────────────
_COSINEX_SATELLITE_RE = re.compile(r"/(?:VMP)?Satellite/notice/")
_RIB_MEINAUFTRAG_RE = re.compile(
    r"meinauftrag\.rib\.de|DetailsByPlatformIdAndTenderId"
)

PlatformFamily = str  # "cosinex_satellite" | "rib_meinauftrag" | "unsupported"


class LockedError(RuntimeError):
    """The platform requires registration/login before documents are visible."""


class UnreachableError(RuntimeError):
    """The platform could not be resolved into a document package (timeout,
    non-200, or HTML that matched neither the open nor the locked shape)."""


class UnsupportedPlatformError(RuntimeError):
    """The document URL's platform family has no adapter in this story."""

    def __init__(self, url: str):
        self.url = url
        self.host = urlparse(url).netloc
        super().__init__(f"No adapter for platform host {self.host!r}: {url}")


def classify_platform(url: str) -> PlatformFamily:
    """Classify by URL *shape*, not bare hostname.

    ``www.evergabe.de`` (its own portal) is ``unsupported``; ``s2.dtvp.de/Satellite/...``
    is ``cosinex_satellite`` — the same underlying cosinex software is deployed
    under many different tenant hostnames.
    """
    if _COSINEX_SATELLITE_RE.search(url):
        return "cosinex_satellite"
    if _RIB_MEINAUFTRAG_RE.search(url):
        return "rib_meinauftrag"
    return "unsupported"


# ── Adapter A: cosinex Satellite / VMPSatellite ──────────────────
_ARCHIVE_LINK_RE = re.compile(r'href="(\./documents/archive/[^"]+\.zip[^"]*)"')


def _resolved_path_last_segment(resolved_url: str) -> str:
    path = urlparse(resolved_url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def fetch_cosinex_satellite(url: str, session: requests.Session) -> bytes:
    """Follow the notice URL and return the Vergabeunterlagen ZIP's bytes.

    cosinex resolves the notice URL, via a session redirect, to either a
    ``.../documents`` page (module unlocked — carries the archive link) or a
    ``.../overview`` page (module locked — no document link exists on it at
    all). The resolved path's last segment is the reliable discriminator;
    the generic "become a registered user" marketing copy that appears on
    *every* cosinex page (including unlocked ones) is not, and was verified
    live to be a false-positive signal.

    Raises ``LockedError`` if the resolved page requires registration, or
    ``UnreachableError`` for any transport failure or unrecognized page shape.
    """
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
    except requests.RequestException as exc:
        raise UnreachableError(f"cosinex request failed: {exc}") from exc

    if r.status_code != 200:
        raise UnreachableError(f"cosinex HTTP {r.status_code} for {url}")

    last_segment = _resolved_path_last_segment(r.url)
    match = _ARCHIVE_LINK_RE.search(r.text)

    if match is None:
        if last_segment == "overview":
            raise LockedError(f"cosinex notice requires registration: {r.url}")
        raise UnreachableError(
            f"cosinex page had no archive link (resolved to {last_segment!r}): {r.url}"
        )

    zip_url = urljoin(r.url, match.group(1))
    try:
        zip_resp = session.get(zip_url, timeout=120)
    except requests.RequestException as exc:
        raise UnreachableError(f"cosinex archive download failed: {exc}") from exc

    if zip_resp.status_code != 200 or not zip_resp.content:
        raise UnreachableError(
            f"cosinex archive download HTTP {zip_resp.status_code} for {zip_url}"
        )
    return zip_resp.content


# ── Adapter B: RIB "mein Auftrag" ────────────────────────────────
# The listing page embeds its document list as a JSON-in-<script> blob, so the
# real HTTP response has JSON-escaped slashes/quotes inside the href (verified
# live: `href=\"https:\/\/my.vergabeplattform.berlin.de\/remote\/download.php...`).
# Unescape those two JSON escapes first, then match plain HTML.
_DOWNLOAD_LINK_RE = re.compile(
    r'href="(https?://[^"]+/remote/download\.php\?k=[^"&]+)[^"]*">([^<]+)<'
)


_UNICODE_ESCAPE_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


def _unescape_json_in_html(text: str) -> str:
    text = text.replace("\\/", "/").replace('\\"', '"')
    return _UNICODE_ESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), text)


_KNOWN_EXTENSIONS = (
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".zip",
    ".x83", ".x81", ".x84", ".txt", ".rtf",
)
_CONTENT_TYPE_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "text/plain": ".txt",
}


def _sanitize_filename(name: str, content_type: str = "") -> str:
    """Sanitize a link's anchor text into a ZIP member name, appending a real
    extension from ``Content-Type`` when the title has none — some real link
    texts are titles like "Tender Documents of Sep 3, 2026 (PDF)" with no
    ``.pdf`` suffix, and ``inventory_zip`` only recognizes files that end in
    ``.pdf`` (or a GAEB extension), so a missing extension would silently drop
    a real document from downstream parsing.
    """
    name = name.strip() or "document"
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name[:200]
    if name.lower().endswith(_KNOWN_EXTENSIONS):
        return name
    extension = _CONTENT_TYPE_EXTENSIONS.get(content_type.split(";")[0].strip().lower())
    return name + extension if extension else name


def fetch_rib_meinauftrag(url: str, session: requests.Session) -> bytes:
    """Follow the notice URL, download every linked document, and return an
    in-memory ZIP's bytes (this family has no bulk archive of its own).

    Raises ``UnreachableError`` for any transport failure or if no downloadable
    document links are found on the resolved page (covers both "genuinely
    unreachable" and "nothing published yet" for this family, since no separate
    locked-page marker was observed here).
    """
    try:
        r = session.get(url, timeout=60, allow_redirects=True)
    except requests.RequestException as exc:
        raise UnreachableError(f"rib request failed: {exc}") from exc

    if r.status_code != 200:
        raise UnreachableError(f"rib HTTP {r.status_code} for {url}")

    links = _DOWNLOAD_LINK_RE.findall(_unescape_json_in_html(r.text))
    if not links:
        raise UnreachableError(f"rib page had no download.php links: {r.url}")

    buffer = io.BytesIO()
    seen_names: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for doc_url, title in links:
            try:
                doc_resp = session.get(doc_url, timeout=120)
            except requests.RequestException:
                continue
            if doc_resp.status_code != 200 or not doc_resp.content:
                continue
            name = _sanitize_filename(title, doc_resp.headers.get("Content-Type", ""))
            if name in seen_names:
                name = f"{name}_{len(seen_names)}"
            seen_names.add(name)
            archive.writestr(name, doc_resp.content)

    if not seen_names:
        raise UnreachableError(f"rib page's document links all failed to download: {r.url}")
    return buffer.getvalue()


# ── Dispatcher ────────────────────────────────────────────────────
def resolve_package(url: str) -> bytes:
    """Classify ``url`` and fetch its document package.

    Raises ``UnsupportedPlatformError`` for out-of-scope platform families,
    ``LockedError`` for registration-gated notices, or ``UnreachableError`` for
    transport/shape failures. The caller (``scripts/enrich_notices.py``) turns
    each of these into a skip+log entry rather than letting the batch abort.
    """
    family = classify_platform(url)
    if family == "unsupported":
        raise UnsupportedPlatformError(url)
    session = requests.Session()
    if family == "cosinex_satellite":
        return fetch_cosinex_satellite(url, session)
    if family == "rib_meinauftrag":
        return fetch_rib_meinauftrag(url, session)
    raise AssertionError(f"unreachable: unknown platform family {family!r}")
