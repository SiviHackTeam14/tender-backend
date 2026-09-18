"""Opt-in semantic checks against Gemini; saves complete responses for human review."""
import json
import os
from pathlib import Path

import pytest
from dotenv import load_dotenv
from pydantic import TypeAdapter

from app.llm.reasoning import analyze
from app.models import CompanyProfile, Tender


@pytest.mark.skipif(os.getenv("RUN_GEMINI_REASONING_TEST") != "1", reason="Opt-in live Gemini reasoning")
def test_same_survivors_different_profiles(tmp_path):
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    profiles = TypeAdapter(list[CompanyProfile]).validate_json((root / "app/data/profiles.json").read_text())
    tenders = TypeAdapter(list[Tender]).validate_json(
        (root / "tests/fixtures/reasoning/comparison-tenders.json").read_text()
    )
    results = {}
    for profile in profiles:
        analyses = analyze(profile, tenders, model="gemini-3.8-flash")
        results[profile.id] = {a.tender_id: a for a in analyses}
        path = tmp_path / f"{profile.id}.json"
        path.write_text(json.dumps([a.model_dump() for a in analyses], ensure_ascii=False, indent=2))
        print(f"Review live Gemini output: {path}")
    a, b = results["profile-a"], results["profile-b"]
    # Broad requirements here have no unstated count/value/lookback thresholds.
    assert a["MOCK-sewer"].criteria.reference_eligibility.status == "PASS"
    assert b["MOCK-school"].criteria.reference_eligibility.status == "PASS"
    assert b["MOCK-sewer"].criteria.reference_eligibility.status == "WARNING"
    assert a["MOCK-school"].criteria.reference_eligibility.status == "WARNING"
    # Explicit exclusion, not merely an absent reference or missing certificate.
    assert b["MOCK-high-voltage"].verdict == "REJECT"
    assert any(a[t.id].verdict != b[t.id].verdict for t in tenders)
    assert a["MOCK-school"].summary != b["MOCK-school"].summary
