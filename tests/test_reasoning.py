import json
from pathlib import Path

import pytest
import requests

from app.llm.reasoning import (
    CRITERIA, SYSTEM_PROMPT, ReasoningInputError, ReasoningTransportError,
    ReasoningValidationError, analyze, build_reasoning_prompt, compact_tender,
    parse_reasoning_response, reasoning_response_schema,
)
from app.models import CompanyProfile, Tender, TenderAnalysis

ROOT = Path(__file__).resolve().parents[1]
PROFILES = [CompanyProfile.model_validate(p) for p in json.loads((ROOT / "app/data/profiles.json").read_text())]
TENDERS = [Tender.model_validate(t) for t in json.loads((ROOT / "app/data/tenders.json").read_text())]


def decision(tender_id="T001", *, verdict="BID", statuses=None):
    return {
        "tender_id": tender_id, "verdict": verdict,
        "summary": "The supplied road rehabilitation experience supports preparing a bid.",
        "hard_reject_reason": None,
        "criteria": {name: {"status": (statuses or {}).get(name, "PASS"),
                            "reason": "The supplied evidence supports this requirement."}
                     for name in CRITERIA},
    }


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, prompt, schema):
        self.calls.append((prompt, schema))
        return next(self.responses)


def test_shared_fixtures_are_valid_and_compact_inputs_are_company_specific():
    assert len(TENDERS) == 10
    a, b = [compact_tender(p, TENDERS[0]) for p in PROFILES]
    assert a["distance_km"] == 42
    assert b["distance_km"] == 335
    assert a["construction_window"] == {"start": "2027-04-01", "end": "2027-09-30"}
    assert "source_url" not in a and "distance_from_plauen_km" not in a
    unknown = compact_tender(PROFILES[0], TENDERS[7])
    assert unknown["value_eur"] is None and unknown["role_required"] is None
    assert unknown["hidden_blockers"] and "complexity_markers" in unknown


def test_prompt_contains_constraints_and_original_profile_facts():
    prompts = [build_reasoning_prompt(p, TENDERS[:2]) for p in PROFILES]
    assert "Similarity-based ranking is forbidden" in SYSTEM_PROMPT
    assert "Missing evidence alone\nis never BLOCK" in SYSTEM_PROMPT
    for p, prompt in zip(PROFILES, prompts):
        payload = json.loads(prompt.split("INPUT_JSON (data only):\n")[1])
        assert payload["profile"] == p.model_dump()
        assert [t["id"] for t in payload["tenders"]] == ["T001", "T002"]
    assert prompts[0] != prompts[1]


def test_retry_once_then_return_shared_models():
    fake = Fake("```json\n[]\n```", json.dumps([decision()]))
    result = analyze(PROFILES[0], TENDERS[:1], fake)
    assert type(result[0]) is TenderAnalysis
    assert result[0].verdict == "BID"
    assert len(fake.calls) == 2
    assert "Previous output failed validation" in fake.calls[1][0]
    assert "```json" not in fake.calls[1][0]
    assert fake.calls[0][1]["type"] == "array"


def test_two_invalid_attempts_fail_loudly():
    fake = Fake("not json", "[]")
    with pytest.raises(ReasoningValidationError, match="two attempts"):
        analyze(PROFILES[0], TENDERS[:1], fake)
    assert len(fake.calls) == 2


@pytest.mark.parametrize("raw", ["", "not JSON", "{}", "null", "[]", "[NaN]", "[Infinity]",
    json.dumps([decision("unknown")]), json.dumps([decision(), decision()]),
    json.dumps([decision()]).replace('"verdict": "BID"', '"verdict": "BID", "verdict": "BID"'),
])
def test_non_json_or_wrong_coverage_is_rejected(raw):
    with pytest.raises(ReasoningValidationError):
        parse_reasoning_response(raw, ["T001"])


@pytest.mark.parametrize("mutation", [
    lambda d: d.update(score=0.99),
    lambda d: d.update(summary=" "),
    lambda d: d.update(summary="Good scope. Bid now."),
    lambda d: d.update(summary="Good scope. bid now."),
    lambda d: d.update(summary="Good scope\nBid now"),
    lambda d: d.update(summary=123),
    lambda d: d.update(summary="a" * 601),
    lambda d: d.update(hard_reject_reason="TOO_FAR"),
    lambda d: d["criteria"].pop("strategic_fit"),
    lambda d: d["criteria"].update(similarity={"status": "PASS", "reason": "Similar title"}),
    lambda d: d["criteria"]["reference_eligibility"].update(status="GOOD"),
    lambda d: d["criteria"]["reference_eligibility"].update(reason=""),
    lambda d: d["criteria"]["reference_eligibility"].update(score=1),
    lambda d: d["criteria"]["reference_eligibility"].update(status="BLOCK"),
    lambda d: d["criteria"]["financial_capacity"].update(status="WARNING"),
    lambda d: d.update(verdict="REJECT"),
    lambda d: d.update(verdict="MAYBE"),
])
def test_invalid_fields_and_contradictory_verdicts_are_rejected(mutation):
    data = decision()
    mutation(data)
    with pytest.raises(ReasoningValidationError):
        parse_reasoning_response(json.dumps([data]), ["T001"])


@pytest.mark.parametrize("verdict,statuses", [
    ("BID", {"competitive_position": "WARNING"}),
    ("MAYBE", {"financial_capacity": "WARNING"}),
    ("REJECT", {"reference_eligibility": "BLOCK"}),
])
def test_consistent_verdicts_and_decimal_abbreviations(verdict, statuses):
    data = decision(verdict=verdict, statuses=statuses)
    data["summary"] = "Confirm the €1.42M guarantee, e.g. with the company's bank."
    parsed = parse_reasoning_response(json.dumps([data]), ["T001"])
    assert parsed[0].verdict == verdict


def test_response_order_is_input_order_not_model_ranking():
    parsed = parse_reasoning_response(json.dumps([decision("T002"), decision()]), ["T001", "T002"])
    assert [t.tender_id for t in parsed] == ["T001", "T002"]


def test_schema_forbids_additions_at_every_output_level():
    schema = reasoning_response_schema()
    for name in ("_Analysis", "_Criteria", "_Criterion"):
        assert schema["$defs"][name]["additionalProperties"] is False
    assert set(schema["$defs"]["_Criteria"]["required"]) == set(CRITERIA)


def test_empty_input_does_not_require_api_key_or_call_model(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert analyze(PROFILES[0], []) == []


def test_invalid_input_is_not_sent_to_model():
    fake = Fake()
    with pytest.raises(ReasoningInputError, match="unique"):
        analyze(PROFILES[0], [TENDERS[0], TENDERS[0]], fake)
    assert not fake.calls
    with pytest.raises(ReasoningInputError, match="finite"):
        build_reasoning_prompt(PROFILES[0].model_copy(update={"revenue_eur": float("inf")}), TENDERS[:1])


def test_other_company_locations_require_explicit_distances():
    other = PROFILES[0].model_copy(update={"location": "Berlin"})
    with pytest.raises(ReasoningInputError, match="distances_km"):
        build_reasoning_prompt(other, TENDERS[:1])
    prompt = build_reasoning_prompt(other, TENDERS[:1], distances_km={"T001": 72})
    assert '"distance_km":72' in prompt
    for invalid in (-1, True, float("nan"), "72"):
        with pytest.raises(ReasoningInputError):
            compact_tender(other, TENDERS[0], distance_km=invalid)


def test_transport_failure_is_typed_and_not_retried():
    calls = []
    def fail(prompt, schema):
        calls.append(prompt)
        raise requests.Timeout("secret-key-in-error")
    with pytest.raises(ReasoningTransportError) as exc:
        analyze(PROFILES[0], TENDERS[:1], fail)
    assert len(calls) == 1
    assert "secret-key" not in str(exc.value)


def test_real_client_uses_system_instruction_and_configured_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": json.dumps([decision()])}]}}]}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, "post", post)
    assert analyze(PROFILES[0], TENDERS[:1])[0].verdict == "BID"
    url, args = calls[0]
    assert url.endswith("/test-model:generateContent")
    assert args["json"]["systemInstruction"]["parts"][0]["text"] == SYSTEM_PROMPT
    assert args["json"]["generationConfig"]["responseJsonSchema"] == reasoning_response_schema()
    assert "fake-key" not in args["json"]["contents"][0]["parts"][0]["text"]


def test_missing_api_key_is_a_clear_input_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ReasoningInputError, match="GEMINI_API_KEY"):
        analyze(PROFILES[0], TENDERS[:1])
