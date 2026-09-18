"""Tests for scripts/prototype.py (Story 1.1).

The module is loaded via importlib from its file path (scripts/ is not a
package) so we can prove import-time safety: no HTTP calls happen just from
loading the module. All network access in these tests is mocked; nothing
here talks to the real oeffentlichevergabe.de API.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest
import requests

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCRIPT_PATH = BACKEND_DIR / "scripts" / "prototype.py"
FIXTURE_ZIP = Path(__file__).resolve().parent / "fixtures" / "notice-export-sample.zip"

REQUIRED_OUTPUT_KEYS = {
    "noticeIdentifier",
    "noticeVersion",
    "noticeType",
    "publicationDate",
    "title",
    "description",
    "estimatedValue",
    "cpvCodes",
    "nutsCodes",
    "location",
    "publicOpeningDate",
}


def _load_prototype_module():
    spec = importlib.util.spec_from_file_location("prototype_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_importing_module_makes_no_network_calls(monkeypatch):
    """Loading the module must not hit the network (main-guard requirement)."""

    def _boom(*args, **kwargs):
        raise AssertionError("scripts/prototype.py must not call requests.get at import time")

    monkeypatch.setattr(requests, "get", _boom)
    module = _load_prototype_module()
    assert hasattr(module, "main")
    assert hasattr(module, "run_pipeline")


@pytest.fixture(scope="module")
def prototype():
    # Loaded once with real `requests` intact; individual tests monkeypatch
    # `prototype.requests.get` for their own mocked scenarios.
    return _load_prototype_module()


@pytest.fixture()
def fixture_zip_bytes() -> bytes:
    return FIXTURE_ZIP.read_bytes()


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content


# ── fetch_day: I/O edge cases ────────────────────────────────────────────
def test_fetch_day_success_returns_tables(monkeypatch, prototype, fixture_zip_bytes):
    monkeypatch.setattr(prototype.requests, "get", lambda *a, **k: _FakeResponse(200, fixture_zip_bytes))
    tables = prototype.fetch_day("2026-09-10")
    assert set(tables.keys()) == {
        "notice", "classification", "placeOfPerformance", "purpose", "organisation", "submissionTerms",
    }
    assert len(tables["notice"]) == 9


def test_fetch_day_non_200_returns_empty_dict(monkeypatch, prototype):
    monkeypatch.setattr(prototype.requests, "get", lambda *a, **k: _FakeResponse(404, b""))
    assert prototype.fetch_day("2026-09-01") == {}


def test_fetch_day_empty_body_returns_empty_dict(monkeypatch, prototype):
    monkeypatch.setattr(prototype.requests, "get", lambda *a, **k: _FakeResponse(200, b""))
    assert prototype.fetch_day("2026-09-01") == {}


def test_fetch_day_request_exception_returns_empty_dict(monkeypatch, prototype):
    def _raise(*args, **kwargs):
        raise prototype.requests.RequestException("timeout")

    monkeypatch.setattr(prototype.requests, "get", _raise)
    assert prototype.fetch_day("2026-09-01") == {}


def test_fetch_day_corrupt_zip_returns_empty_dict(monkeypatch, prototype):
    monkeypatch.setattr(prototype.requests, "get", lambda *a, **k: _FakeResponse(200, b"not a zip file"))
    assert prototype.fetch_day("2026-09-01") == {}


def test_fetch_all_days_continues_past_bad_days(monkeypatch, prototype, fixture_zip_bytes):
    """One bad day (per matrix: 404/timeout/corrupt) must not abort the window."""
    calls = {"n": 0}

    def _flaky_get(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            return _FakeResponse(404, b"")
        return _FakeResponse(200, fixture_zip_bytes)

    monkeypatch.setattr(prototype.requests, "get", _flaky_get)
    tables = prototype.fetch_all_days(days_back=4)
    assert calls["n"] == 4
    # Two good days x 9 notice rows each.
    assert len(tables["notice"]) == 18


# ── run_pipeline against the joined fixture ──────────────────────────────
def _pipeline_survivors(prototype):
    tables = prototype.parse_zip_tables(FIXTURE_ZIP.read_bytes())
    return prototype.run_pipeline(tables, today=date(2026, 9, 18), verbose=False)


def test_survivors_have_exact_required_keys(prototype):
    survivors, _counts = _pipeline_survivors(prototype)
    assert len(survivors) > 0
    for survivor in survivors:
        assert set(survivor.keys()) == REQUIRED_OUTPUT_KEYS


def test_survivor_ids_match_expected_set(prototype):
    survivors, _counts = _pipeline_survivors(prototype)
    ids = {(s["noticeIdentifier"], s["noticeVersion"]) for s in survivors}
    assert ids == {
        ("notice-happy", "01"),
        ("notice-lot-cpv", "01"),
        ("notice-nuts-fallback", "01"),
        ("notice-dup", "10"),
    }


def test_wrong_type_cpv_nuts_and_expired_are_excluded(prototype):
    survivors, counts = _pipeline_survivors(prototype)
    ids = {s["noticeIdentifier"] for s in survivors}
    assert "notice-wrong-type" not in ids
    assert "notice-wrong-cpv" not in ids
    assert "notice-wrong-nuts" not in ids
    assert "notice-expired" not in ids
    assert counts["fetched"] == 9


def test_lot_only_cpv_is_kept_and_cpv_comes_from_joined_table(prototype):
    """A notice whose CPV45 is only on a lot row (not notice-level) must survive,
    and cpvCodes must be sourced from classification.csv, not invented."""
    survivors, _counts = _pipeline_survivors(prototype)
    lot = next(s for s in survivors if s["noticeIdentifier"] == "notice-lot-cpv")
    assert "45262100" in lot["cpvCodes"]
    assert "71000000" in lot["cpvCodes"]  # notice-level code is still unioned in, just not construction-only
    # Title/description fall back to the first lot row since no notice-level purpose row exists.
    assert lot["title"] == "Gerüstbau Los 1"
    assert lot["nutsCodes"] == ["DE221"]
    assert lot["location"] == "Passau"
    assert lot["publicOpeningDate"] is None  # no submissionTerms row -> unknown, kept


def test_nuts_fallback_uses_buyer_organisation(prototype):
    """No placeOfPerformance rows -> nutsCodes/location fall back to the buyer org."""
    survivors, _counts = _pipeline_survivors(prototype)
    nf = next(s for s in survivors if s["noticeIdentifier"] == "notice-nuts-fallback")
    assert nf["nutsCodes"] == ["DE271"]
    assert nf["location"] == "Augsburg"
    assert nf["estimatedValue"] is None  # blank estimatedValue in purpose.csv -> null, never invented
    # Invalid date string is kept, and passed through untouched.
    assert nf["publicOpeningDate"] == "invalid-date-string"


def test_dedup_keeps_highest_numeric_version_not_lexicographic(prototype):
    """"9" vs "10": string comparison would wrongly rank "9" as newer."""
    survivors, _counts = _pipeline_survivors(prototype)
    dup = next(s for s in survivors if s["noticeIdentifier"] == "notice-dup")
    assert dup["noticeVersion"] == "10"
    assert dup["title"] == "Neue Version"
    assert dup["publicationDate"] == "2026-09-13T00:00:00+02:00"


def test_expired_deadline_dropped_unknown_kept(prototype):
    survivors, _counts = _pipeline_survivors(prototype)
    ids = {s["noticeIdentifier"] for s in survivors}
    assert "notice-expired" not in ids  # past publicOpeningDate -> dropped
    happy = next(s for s in survivors if s["noticeIdentifier"] == "notice-happy")
    assert happy["publicOpeningDate"] == "2026-12-01T10:00:00+01:00"


def test_stage_counts_are_monotonically_non_increasing(prototype):
    _survivors, counts = _pipeline_survivors(prototype)
    stages = ["fetched", "competition", "cpv45", "region", "still_open"]
    values = [counts[s] for s in stages]
    assert values == sorted(values, reverse=True)
    assert counts["deduped"] <= counts["still_open"]
    assert counts["capped"] == counts["deduped"]  # well under MAX_FETCH here


# ── dedup / cap / deadline-fallback logic on synthetic tables ───────────
def test_max_fetch_caps_to_newest_publication_date(prototype):
    n = 600
    notices = [
        dict(
            noticeIdentifier=f"synthetic-{i}",
            noticeVersion="1",
            noticeType="cn-standard",
            publicationDate=f"2026-01-{(i % 28) + 1:02d}T00:00:00+01:00",
        )
        for i in range(n)
    ]
    classification = [
        dict(noticeIdentifier=f"synthetic-{i}", noticeVersion="1", lotIdentifier="",
             classificationType="cpv", mainClassificationCode="45210000", additionalClassificationCodes="")
        for i in range(n)
    ]
    place = [
        dict(noticeIdentifier=f"synthetic-{i}", noticeVersion="1", lotIdentifier="",
             placePerformanceCountrySubdivision="DE211", placePerformanceCity="München")
        for i in range(n)
    ]
    tables = {
        "notice": notices,
        "classification": classification,
        "placeOfPerformance": place,
        "purpose": [],
        "organisation": [],
        "submissionTerms": [],
    }
    survivors, counts = prototype.run_pipeline(tables, today=date(2026, 1, 1), verbose=False)
    assert counts["deduped"] == n
    assert counts["capped"] == prototype.MAX_FETCH
    assert len(survivors) == prototype.MAX_FETCH
    # Newest publicationDate (Jan 28) must be kept over oldest (Jan 1).
    kept_days = {s["publicationDate"][8:10] for s in survivors}
    assert "28" in kept_days
    assert max(kept_days) >= "23"  # top MAX_FETCH of 600 skews toward the newest days


def test_missing_submission_terms_table_skips_deadline_filter(prototype):
    """If submissionTerms cannot be joined at all, keep-all (skip the filter)."""
    tables = {
        "notice": [
            dict(noticeIdentifier="n1", noticeVersion="1", noticeType="cn-standard",
                 publicationDate="2026-01-01T00:00:00+01:00"),
        ],
        "classification": [
            dict(noticeIdentifier="n1", noticeVersion="1", lotIdentifier="",
                 classificationType="cpv", mainClassificationCode="45210000", additionalClassificationCodes=""),
        ],
        "placeOfPerformance": [
            dict(noticeIdentifier="n1", noticeVersion="1", lotIdentifier="",
                 placePerformanceCountrySubdivision="DE211", placePerformanceCity="München"),
        ],
        "purpose": [],
        "organisation": [],
        # submissionTerms key intentionally absent entirely.
    }
    survivors, counts = prototype.run_pipeline(tables, today=date(2026, 1, 1), verbose=False)
    assert counts["still_open"] == 1
    assert len(survivors) == 1
    assert survivors[0]["publicOpeningDate"] is None


def test_parse_version_treats_leading_zero_same_as_bare_int(prototype):
    assert prototype.parse_version("01") == prototype.parse_version("1") == 1


# ── main() writes the output file without touching real network ─────────
def test_main_writes_output_json(monkeypatch, tmp_path, prototype, fixture_zip_bytes):
    monkeypatch.setattr(prototype.requests, "get", lambda *a, **k: _FakeResponse(200, fixture_zip_bytes))
    monkeypatch.setattr(prototype, "FETCH_DAYS_BACK", 1)

    fake_scripts_dir = tmp_path / "scripts"
    fake_scripts_dir.mkdir()
    monkeypatch.setattr(prototype, "__file__", str(fake_scripts_dir / "prototype.py"))

    prototype.main()

    out_path = tmp_path / "data" / "raw_notices.json"
    assert out_path.exists()

    import json

    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) > 0
    for entry in data:
        assert set(entry.keys()) == REQUIRED_OUTPUT_KEYS
