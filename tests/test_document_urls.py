from pathlib import Path

import pytest
import requests

from app.fetch.document_urls import (
    OCDS_ACCEPT,
    extract_document_urls,
    fetch_ocds_day,
    get_document_urls_for_notice,
    index_ocds_zip,
)

FIXTURE_ZIP = Path(__file__).resolve().parent / "fixtures" / "ocds-sample" / "2026-09-16.ocds.zip"

COSINEX_NOTICE = "aaaaaaaa-0000-0000-0000-000000000001"
RIB_NOTICE = "bbbbbbbb-0000-0000-0000-000000000002"
NONE_NOTICE = "cccccccc-0000-0000-0000-000000000003"


@pytest.fixture()
def zip_bytes() -> bytes:
    return FIXTURE_ZIP.read_bytes()


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


def test_fetch_ocds_day_sends_ocds_accept_header(monkeypatch, zip_bytes):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["headers"] = headers
        captured["params"] = params
        return _FakeResponse(200, zip_bytes)

    monkeypatch.setattr(requests, "get", fake_get)
    result = fetch_ocds_day("2026-09-16")
    assert result == zip_bytes
    assert captured["headers"]["Accept"] == OCDS_ACCEPT
    assert captured["params"]["pubDay"] == "2026-09-16"


@pytest.mark.parametrize(
    "response",
    [
        _FakeResponse(404, b""),
        _FakeResponse(200, b""),
    ],
)
def test_fetch_ocds_day_skips_on_failure(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *a, **k: response)
    assert fetch_ocds_day("2026-09-16") == b""


def test_fetch_ocds_day_skips_on_request_exception(monkeypatch):
    def boom(*a, **k):
        raise requests.RequestException("timeout")

    monkeypatch.setattr(requests, "get", boom)
    assert fetch_ocds_day("2026-09-16") == b""


def test_index_ocds_zip_parses_version_int(zip_bytes):
    index = index_ocds_zip(zip_bytes)
    assert index[COSINEX_NOTICE] == {1: f"{COSINEX_NOTICE}-01.json"}
    # RIB fixture entry is named "-1.json" (not zero-padded) -> same int key
    assert index[RIB_NOTICE] == {1: f"{RIB_NOTICE}-1.json"}


def test_extract_document_urls_cosinex_shape(zip_bytes):
    index = index_ocds_zip(zip_bytes)
    filename = index[COSINEX_NOTICE][1]
    docs = extract_document_urls(zip_bytes, filename)
    assert len(docs) == 1
    assert "Satellite/notice/" in docs[0]["url"]


def test_extract_document_urls_no_documents_returns_empty_list(zip_bytes):
    index = index_ocds_zip(zip_bytes)
    filename = index[NONE_NOTICE][1]
    assert extract_document_urls(zip_bytes, filename) == []


def test_get_document_urls_for_notice_matches_by_identifier_and_version(zip_bytes):
    docs = get_document_urls_for_notice(zip_bytes, COSINEX_NOTICE, "01")
    assert len(docs) == 1
    docs_unpadded_version = get_document_urls_for_notice(zip_bytes, RIB_NOTICE, "1")
    assert len(docs_unpadded_version) == 1


def test_get_document_urls_for_notice_no_match_returns_empty_list(zip_bytes):
    assert get_document_urls_for_notice(zip_bytes, "not-a-real-id", "01") == []
    # Wrong version for a real notice -> also no match, not an error.
    assert get_document_urls_for_notice(zip_bytes, COSINEX_NOTICE, "99") == []
