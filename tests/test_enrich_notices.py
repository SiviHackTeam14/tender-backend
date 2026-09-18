"""Tests for scripts/enrich_notices.py (Story 1.2).

Loaded via importlib from its file path (scripts/ is not a package), same
convention as tests/test_fetch.py for scripts/prototype.py. All network
access (OCDS fetch, platform hops) is mocked; nothing here talks to the real
oeffentlichevergabe.de API or Gemini.
"""
from __future__ import annotations

import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "enrich_notices.py"
OCDS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ocds-sample" / "2026-09-16.ocds.zip"
ROLANDBRUNNEN_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "rolandbrunnen-sample.zip"

COSINEX_NOTICE = "aaaaaaaa-0000-0000-0000-000000000001"
RIB_NOTICE = "bbbbbbbb-0000-0000-0000-000000000002"
NONE_NOTICE = "cccccccc-0000-0000-0000-000000000003"


def _load_enrich_module():
    spec = importlib.util.spec_from_file_location("enrich_notices_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_importing_module_makes_no_network_calls(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("scripts/enrich_notices.py must not call requests.get at import time")

    monkeypatch.setattr(requests, "get", _boom)
    module = _load_enrich_module()
    assert hasattr(module, "main")
    assert hasattr(module, "run_pipeline")


@pytest.fixture(scope="module")
def enrich():
    return _load_enrich_module()


def _notice(notice_id: str, day: str = "2026-09-16") -> dict:
    return {
        "noticeIdentifier": notice_id,
        "noticeVersion": "01",
        "noticeType": "cn-standard",
        "publicationDate": f"{day}T00:00:00+02:00",
        "title": "Test tender",
        "description": "Test description",
        "estimatedValue": None,
        "cpvCodes": ["45000000"],
        "nutsCodes": ["DE212"],
        "location": "Teststadt",
        "publicOpeningDate": None,
    }


@pytest.fixture()
def ocds_zip_bytes() -> bytes:
    return OCDS_FIXTURE.read_bytes()


@pytest.fixture()
def rolandbrunnen_zip_bytes() -> bytes:
    return ROLANDBRUNNEN_FIXTURE.read_bytes()


# ── group_by_day / log_event (pure helpers) ──────────────────────────────
def test_group_by_day_groups_by_publication_date_prefix(enrich):
    notices = [_notice(COSINEX_NOTICE, "2026-09-16"), _notice(RIB_NOTICE, "2026-09-17")]
    grouped = enrich.group_by_day(notices)
    assert set(grouped.keys()) == {"2026-09-16", "2026-09-17"}
    assert len(grouped["2026-09-16"]) == 1


def test_log_event_writes_one_json_line(enrich):
    buffer = io.StringIO()
    enrich.log_event(buffer, _notice(COSINEX_NOTICE), "platform_fetch", "skipped", "login_required", "example.de")
    line = json.loads(buffer.getvalue().strip())
    assert line == {
        "noticeIdentifier": COSINEX_NOTICE,
        "noticeVersion": "01",
        "stage": "platform_fetch",
        "status": "skipped",
        "reason": "login_required",
        "host": "example.de",
    }


# ── enrich_one: per-notice edge cases ─────────────────────────────────────
def test_enrich_one_no_document_urls_is_skipped(enrich, tmp_path):
    log = io.StringIO()
    record = enrich.enrich_one(_notice(NONE_NOTICE), [], enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "skipped"
    assert record["extraction_skip_reason"] == "no_document_url"
    assert record["document_url"] is None
    assert record["trade_type"] is None
    assert "no_document_url" in log.getvalue()


def test_enrich_one_locked_platform_is_skipped(enrich, tmp_path, monkeypatch):
    def fake_resolve(url):
        raise enrich.LockedError("locked")

    monkeypatch.setattr(enrich, "resolve_package", fake_resolve)
    log = io.StringIO()
    docs = [{"url": "https://x.example.de/Satellite/notice/CXTEST/documents"}]
    record = enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "skipped"
    assert record["extraction_skip_reason"] == "login_required"
    assert "login_required" in log.getvalue()


def test_enrich_one_unsupported_platform_is_skipped(enrich, tmp_path, monkeypatch):
    def fake_resolve(url):
        raise enrich.UnsupportedPlatformError(url)

    monkeypatch.setattr(enrich, "resolve_package", fake_resolve)
    log = io.StringIO()
    docs = [{"url": "https://www.evergabe.de/auftraege/x/1"}]
    record = enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "skipped"
    assert record["extraction_skip_reason"] == "unsupported_platform"


def test_enrich_one_unreachable_platform_is_skipped(enrich, tmp_path, monkeypatch):
    def fake_resolve(url):
        raise enrich.UnreachableError("boom")

    monkeypatch.setattr(enrich, "resolve_package", fake_resolve)
    log = io.StringIO()
    docs = [{"url": "https://x.example.de/Satellite/notice/CXTEST/documents"}]
    record = enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "skipped"
    assert record["extraction_skip_reason"] == "platform_unreachable"


def test_enrich_one_success_with_stub_generate_yields_null_fields(enrich, tmp_path, monkeypatch, rolandbrunnen_zip_bytes):
    monkeypatch.setattr(enrich, "resolve_package", lambda url: rolandbrunnen_zip_bytes)
    log = io.StringIO()
    docs = [{"url": "https://x.example.de/Satellite/notice/CXTEST/documents"}]
    record = enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "ok"
    assert record["extraction_method"] == "gaeb"
    assert record["document_url"] == docs[0]["url"]
    assert record["local_zip_path"] == f"{tmp_path.name}/{COSINEX_NOTICE}.zip"
    # Stub generator -> every extraction field is null/empty, never invented.
    assert record["trade_type"] is None
    assert record["certifications_required"] == []
    # 1.1 fields must survive untouched.
    assert record["title"] == "Test tender"


def test_enrich_one_caches_downloaded_package(enrich, tmp_path, monkeypatch, rolandbrunnen_zip_bytes):
    calls = {"n": 0}

    def fake_resolve(url):
        calls["n"] += 1
        return rolandbrunnen_zip_bytes

    monkeypatch.setattr(enrich, "resolve_package", fake_resolve)
    docs = [{"url": "https://x.example.de/Satellite/notice/CXTEST/documents"}]
    log = io.StringIO()
    enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert calls["n"] == 1
    cache_path = tmp_path / f"{COSINEX_NOTICE}.zip"
    assert cache_path.exists()

    # Second call for the same notice must use the cache, not the network.
    enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert calls["n"] == 1


def test_enrich_one_parse_failure_marks_failed_not_skipped(enrich, tmp_path, monkeypatch):
    empty_zip_buffer = io.BytesIO()
    with zipfile.ZipFile(empty_zip_buffer, "w") as z:
        z.writestr("readme.txt", "no pdfs or gaeb here")
    monkeypatch.setattr(enrich, "resolve_package", lambda url: empty_zip_buffer.getvalue())
    docs = [{"url": "https://x.example.de/Satellite/notice/CXTEST/documents"}]
    log = io.StringIO()
    record = enrich.enrich_one(_notice(COSINEX_NOTICE), docs, enrich.stub_generate, None, tmp_path, log)
    assert record["extraction_status"] == "failed"
    assert "parse_failed" in record["extraction_skip_reason"]


# ── run_pipeline: OCDS-day grouping + skip/log behavior ──────────────────
def test_run_pipeline_ocds_fetch_failure_skips_whole_day(enrich, tmp_path):
    notices = [_notice(COSINEX_NOTICE)]
    log = io.StringIO()
    enriched, counts = enrich.run_pipeline(
        notices, enrich.stub_generate, None, tmp_path, log, fetch_day=lambda day: b""
    )
    assert counts["ocds_fetch_failed"] == 1
    assert enriched[0]["extraction_status"] == "skipped"
    assert enriched[0]["extraction_skip_reason"] == "ocds_fetch_failed"


def test_run_pipeline_end_to_end_with_mocked_ocds_and_platform(
    enrich, tmp_path, monkeypatch, ocds_zip_bytes, rolandbrunnen_zip_bytes
):
    notices = [_notice(COSINEX_NOTICE), _notice(RIB_NOTICE), _notice(NONE_NOTICE)]
    monkeypatch.setattr(enrich, "resolve_package", lambda url: rolandbrunnen_zip_bytes)
    log = io.StringIO()

    enriched, counts = enrich.run_pipeline(
        notices, enrich.stub_generate, None, tmp_path, log, fetch_day=lambda day: ocds_zip_bytes
    )

    by_id = {r["noticeIdentifier"]: r for r in enriched}
    assert by_id[COSINEX_NOTICE]["extraction_status"] == "ok"
    assert by_id[RIB_NOTICE]["extraction_status"] == "ok"
    assert by_id[NONE_NOTICE]["extraction_status"] == "skipped"
    assert by_id[NONE_NOTICE]["extraction_skip_reason"] == "no_document_url"
    assert counts["ok"] == 2
    assert counts["skipped"] == 1


# ── main(): writes output files without touching the real network ───────
def test_main_writes_enriched_json_and_log(enrich, tmp_path, monkeypatch, ocds_zip_bytes, rolandbrunnen_zip_bytes):
    raw_notices_path = tmp_path / "raw_notices.json"
    raw_notices_path.write_text(json.dumps([_notice(COSINEX_NOTICE)]), encoding="utf-8")

    monkeypatch.setattr(enrich, "RAW_NOTICES_PATH", raw_notices_path)
    monkeypatch.setattr(enrich, "ENRICHED_PATH", tmp_path / "enriched_notices.json")
    monkeypatch.setattr(enrich, "LOG_PATH", tmp_path / "enrichment-log.jsonl")
    monkeypatch.setattr(enrich, "PACKAGES_DIR", tmp_path / "lv_packages")
    monkeypatch.setattr(enrich, "fetch_ocds_day", lambda day: ocds_zip_bytes)
    monkeypatch.setattr(enrich, "resolve_package", lambda url: rolandbrunnen_zip_bytes)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    enrich.main()

    out_path = tmp_path / "enriched_notices.json"
    assert out_path.exists()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["extraction_status"] == "ok"
    assert (tmp_path / "enrichment-log.jsonl").exists()


def test_main_raises_clear_error_when_raw_notices_missing(enrich, tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "RAW_NOTICES_PATH", tmp_path / "does-not-exist.json")
    with pytest.raises(SystemExit, match="run scripts/prototype.py"):
        enrich.main()
