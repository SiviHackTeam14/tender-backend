import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.llm.extraction import ExtractedRequirements, ExtractionError, extract_chunk, extract_pages

FIXTURES = Path(__file__).parent / "fixtures" / "extraction"


def empty():
    return {name: [] if name in {"certifications_required", "complexity_markers", "hidden_blockers"}
            else None for name in ExtractedRequirements.model_fields}


class Fake:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def __call__(self, prompt, schema):
        self.calls.append(prompt)
        return next(self.responses)


def test_retry_then_success():
    fake = Fake("not json", json.dumps(empty()))
    assert extract_chunk("Gewerk nicht angegeben.", fake).estimated_value_eur is None
    assert len(fake.calls) == 2
    assert "Previous output failed validation" in fake.calls[1]


def test_retry_fails_loudly():
    fake = Fake("```json\n{}\n```", "{}")
    with pytest.raises(ExtractionError, match="two attempts"):
        extract_chunk("Text", fake)
    assert len(fake.calls) == 2


@pytest.mark.parametrize("verdict", ["ACCEPT", "BID", "MAYBE", "REJECT"])
def test_extraction_retries_and_discards_suitability_output(verdict):
    fake = Fake(json.dumps(empty() | {"verdict": verdict}), json.dumps(empty()))
    result = extract_chunk("Keine explizite Auftragssumme genannt.", fake)
    assert set(result.model_dump()) == set(empty())
    assert result.estimated_value_eur is None
    assert len(fake.calls) == 2


@pytest.mark.parametrize("field,value", [
    ("role_required", "either"), ("estimated_value_eur", "1000"),
    ("estimated_value_eur", -1), ("estimated_value_eur", float("nan")),
    ("eigenleistung_min_pct", 101), ("construction_window_start", "2026-02-30"),
    ("construction_window_start", "20260901"), ("unexpected", True),
])
def test_strict_schema(field, value):
    data = empty()
    data[field] = value
    with pytest.raises(ValidationError):
        ExtractedRequirements.model_validate(data)


def test_requirement_beyond_page_ten():
    late = empty() | {"certifications_required": ["ISO 9001"]}
    fake = Fake(*([json.dumps(empty())] * 10 + [json.dumps(late)]))
    pages = [("late.txt", i, f"Page {i}") for i in range(1, 11)]
    pages.append(("late.txt", 11, "ISO 9001 ist zwingend erforderlich."))
    result, audit = extract_pages(pages, fake)
    assert result.certifications_required == ["ISO 9001"]
    assert audit["pages_processed"] == 11
    assert 11 in audit["chunks"][-1]["source_pages"]
    assert "ISO 9001" in fake.calls[-1]


def test_conflicts_and_deduplication():
    a = empty() | {"estimated_value_eur": 100, "certifications_required": ["ISO 9001"]}
    b = a | {"estimated_value_eur": 200}
    result, audit = extract_pages([("a", 1, "A"), ("b", 1, "B")], Fake(json.dumps(a), json.dumps(b)))
    assert result.estimated_value_eur is None
    assert result.certifications_required == ["ISO 9001"]
    assert audit["conflicts"]["estimated_value_eur"] == [100, 200]
    assert audit["requires_review"]


def test_chunk_coverage_and_overlap():
    text = "abcdefghijklmnopqrstuvwxyz"
    fake = Fake(*([json.dumps(empty())] * 4))
    _, audit = extract_pages([("a", 1, text)], fake, chunk_chars=10, overlap=2)
    assert [c["offset"] for c in audit["chunks"]] == [0, 8, 16]
    assert audit["chunks"][-1]["source"] == text[16:]


@pytest.mark.parametrize("pages", [[], [("scan.pdf", 1, " ")]])
def test_unreadable_input(pages):
    with pytest.raises(ExtractionError):
        extract_pages(pages, Fake())


def test_transport_errors_not_retried():
    calls = []
    def fail(prompt, schema):
        calls.append(prompt)
        raise ExtractionError("HTTP 429")
    with pytest.raises(ExtractionError, match="429"):
        extract_chunk("Text", fail)
    assert len(calls) == 1


@pytest.mark.parametrize("name", ["explicit", "unknown", "restrictions"])
def test_fixture_replay(name):
    """Tests the pipeline using authored responses, not actual model extraction quality."""
    source = (FIXTURES / f"{name}.txt").read_text()
    responses = json.loads((FIXTURES / f"{name}.replay.json").read_text())
    result, audit = extract_pages([(name, 1, source)], Fake(*map(json.dumps, responses)))
    assert result.model_dump() == responses[0]
    assert audit["complete"]


def test_gemini_transport(monkeypatch):
    from app.llm.extraction import GeminiClient
    import requests
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"text": "internal", "thought": True}, {"text": json.dumps(empty())}
            ]}}]}
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(requests, "post", post)
    result = extract_chunk("Test source", GeminiClient("fake-key", "test-model"))
    assert result.role_required is None
    url, args = calls[0]
    assert url.endswith("/test-model:generateContent")
    assert args["headers"]["x-goog-api-key"] == "fake-key"
    assert args["json"]["generationConfig"]["responseMimeType"] == "application/json"


def test_cli_replay(tmp_path):
    import subprocess
    import sys
    audit = tmp_path / "audit.json"
    result = subprocess.run([
        sys.executable, "scripts/extract_tender.py", str(FIXTURES / "unknown.txt"),
        "--replay", str(FIXTURES / "unknown.replay.json"), "--audit", str(audit),
    ], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["estimated_value_eur"] is None
    assert json.loads(audit.read_text())["mode"] == "replay"


def test_http_error_detail_redacts_key():
    from app.llm.extraction import check_gemini_response
    class Response:
        status_code = 404
        def json(self):
            return {"error": {"message": "model missing for secret-key"}}
    with pytest.raises(ExtractionError) as exc:
        check_gemini_response(Response(), "secret-key")
    assert "model missing" in str(exc.value)
    assert "secret-key" not in str(exc.value)
    assert "--list-models" in str(exc.value)


def test_list_models_pagination(monkeypatch):
    from app.llm.extraction import list_gemini_models
    import requests
    pages = iter([
        {"models": [{"name": "models/test-flash", "supportedGenerationMethods": ["generateContent"]}], "nextPageToken": "next"},
        {"models": [{"name": "models/embed", "supportedGenerationMethods": ["embedContent"]}]},
    ])
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return next(pages)
    def get(url, **kwargs):
        calls.append(dict(kwargs["params"]))
        return Response()
    monkeypatch.setattr(requests, "get", get)
    assert list_gemini_models("fake") == ["test-flash"]
    assert calls[1]["pageToken"] == "next"


def test_packed_pages_keep_context_and_file_boundaries():
    fake = Fake(json.dumps(empty()), json.dumps(empty()))
    _, audit = extract_pages([("a.pdf", 1, "first"), ("a.pdf", 2, "second"),
                              ("b.pdf", 1, "third")], fake, pack_pages=True)
    assert len(fake.calls) == 2
    assert "[Page 1]\nfirst" in fake.calls[0]
    assert "[Page 2]\nsecond" in fake.calls[0]
    assert audit["pages_processed"] == 3
    assert audit["chunks"][0]["source_pages"] == [1, 2]


def test_text_requirements_are_combined_with_provenance():
    a = empty() | {"trade_type": "Heizung", "references_required": "Drei Referenzen aus fünf Jahren"}
    b = empty() | {"trade_type": "Elektrotechnik", "references_required": "Selektivitätsstudie aus drei Jahren"}
    result, audit = extract_pages([("a", 1, "A"), ("b", 2, "B")], Fake(json.dumps(a), json.dumps(b)))
    assert result.trade_type == "Heizung; Elektrotechnik"
    assert result.references_required == "Drei Referenzen aus fünf Jahren\nSelektivitätsstudie aus drei Jahren"
    assert audit["aggregated_fields"]["trade_type"] == ["Heizung", "Elektrotechnik"]
    assert audit["field_status"]["trade_type"] == "needs_review"
    assert audit["field_status"]["estimated_value_eur"] == "not_found"
    assert audit["requires_review"]
    assert "trade_type" in audit["review_reasons"]
    assert [chunk["file"] for chunk in audit["chunks"]] == ["a", "b"]


def test_progress_matches_actual_chunks():
    events = []
    fake = Fake(*([json.dumps(empty())] * 3))
    extract_pages([("a", 1, "abcdefghijklmnopqrstuvwxyz")], fake,
                  chunk_chars=10, overlap=2, progress=lambda done, total: events.append((done, total)))
    assert events == [(0, 3), (1, 3), (2, 3), (3, 3)]


def test_real_scalar_conflict_stays_distinct_from_unknown():
    a = empty() | {"role_required": "main_contractor"}
    b = empty() | {"role_required": "subcontractor"}
    result, audit = extract_pages([("a", 1, "A"), ("b", 1, "B")], Fake(json.dumps(a), json.dumps(b)))
    assert result.role_required is None
    assert audit["field_status"]["role_required"] == "conflict"
    assert audit["field_status"]["estimated_value_eur"] == "not_found"
    assert audit["requires_review"]


@pytest.mark.parametrize("pack_pages", [True, False])
def test_cross_page_requirement_keeps_context(pack_pages):
    label = "Geschätzter Gesamtauftragswert:"
    # End page 1 exactly at the packed chunk boundary.
    first = "A" * (12000 - len("[Page 1]\n") - len(label)) + label
    second = "500.000 EUR\n" + "B" * 1000
    prompts = []
    def generate(prompt, schema):
        source = prompt.split("\nSOURCE:\n", 1)[1]
        prompts.append(source)
        fields = empty()
        if label in source and "500.000 EUR" in source:
            fields["estimated_value_eur"] = 500000
        return json.dumps(fields)
    result, audit = extract_pages([("LV.pdf", 1, first), ("LV.pdf", 2, second)],
                                  generate, pack_pages=pack_pages)
    assert result.estimated_value_eur == 500000
    assert all(len(p) <= 12000 for p in prompts)
    assert any(chunk["source_pages"] == [1, 2] for chunk in audit["chunks"])


def test_chunk_sources_exclude_nonoverlapping_pages():
    prompts = []
    def generate(prompt, schema):
        prompts.append(prompt.split("\nSOURCE:\n", 1)[1])
        return json.dumps(empty())
    pages = [("a.pdf", 1, "A" * 30), ("a.pdf", 2, "B" * 30), ("b.pdf", 1, "C" * 30)]
    _, audit = extract_pages(pages, generate, chunk_chars=30, overlap=10, pack_pages=True)
    a_chunks = [c for c in audit["chunks"] if c["file"] == "a.pdf"]
    assert a_chunks[-1]["source_pages"] == [2]
    for prev, nxt in zip(a_chunks, a_chunks[1:]):
        assert prev["source"][-10:] == nxt["source"][:10]
    assert all("A" not in c["source"] and "B" not in c["source"] for c in audit["chunks"] if c["file"] == "b.pdf")


def test_conflicting_text_requires_review_without_losing_findings():
    a = empty() | {"references_required": "Keine Referenzen erforderlich."}
    b = empty() | {"references_required": "Drei Referenzen zwingend erforderlich."}
    result, audit = extract_pages([("a", 1, "A"), ("b", 1, "B")], Fake(json.dumps(a), json.dumps(b)))
    assert "Keine Referenzen" in result.references_required
    assert "Drei Referenzen" in result.references_required
    assert audit["requires_review"] is True
    assert audit["field_status"]["references_required"] == "needs_review"
    assert "references_required" in audit["review_reasons"]
