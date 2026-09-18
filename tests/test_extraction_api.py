import io
import json
import time
from threading import Event
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from app.api.extractions import get_generator, get_jobs
from app.main import app
from app.services.extraction_jobs import ExtractionJobs
from tests.test_extraction import empty


def small_pdf():
    stream = b"BT /F1 12 Tf 50 750 Td (Malerarbeiten ohne Auftragswert) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(n).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    return pdf + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def archive():
    result = io.BytesIO()
    with ZipFile(result, "w") as z:
        z.writestr("LV.pdf", small_pdf())
        # A broken, excluded PDF must not be opened.
        z.writestr("Datenschutz.pdf", b"not a PDF")
    return result.getvalue()


class Generator:
    model = "gemini-3.8-flash"
    def __init__(self):
        self.fail = False
        self.block = False
        self.started = Event()
        self.release = Event()
        self.calls = 0

    def __call__(self, prompt, schema):
        self.calls += 1
        if "documents" in schema["properties"]:
            self.started.set()
            if self.block:
                assert self.release.wait(5)
            return json.dumps({"documents": [
                {"id": 0, "decision": "include", "relevant_fields": ["trade_type"], "reason": "LV"},
                {"id": 1, "decision": "exclude", "relevant_fields": [], "reason": "Datenschutz"},
            ]})
        return "broken" if self.fail else json.dumps(empty() | {"trade_type": "Malerarbeiten"})


@pytest.fixture
def setup_api():
    jobs = ExtractionJobs(workers=1)
    generate = Generator()
    app.dependency_overrides[get_jobs] = lambda: jobs
    app.dependency_overrides[get_generator] = lambda: generate
    with TestClient(app) as client:
        try:
            yield client, jobs, generate
        finally:
            generate.release.set()
            jobs.close()
            app.dependency_overrides.clear()


def upload(client):
    return client.post("/api/extractions", files={"file": ("tender.zip", archive(), "application/zip")})


def finished(client, url):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = client.get(url)
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    pytest.fail("Job did not finish")


def test_upload_poll_result_and_audit(setup_api):
    client, jobs, generate = setup_api
    response = upload(client)
    assert response.status_code == 202
    accepted = response.json()
    assert response.headers["location"] == accepted["status_url"]
    job = finished(client, accepted["status_url"])
    assert job["status"] == "completed", job
    assert job["progress"] == {"completed_chunks": 1, "total_chunks": 1}
    result = job["result"]
    assert result["fields"]["trade_type"] == "Malerarbeiten"
    assert result["fields"]["estimated_value_eur"] is None
    assert result["field_status"]["estimated_value_eur"] == "not_found"
    assert result["evidence"]["trade_type"][0]["file"] == "LV.pdf"
    assert result["evidence"]["trade_type"][0]["pages"] == [1]
    assert result["documents"][1]["decision"] == "exclude"
    assert result["coverage"] == "selected_pdfs_only"
    assert generate.calls == 2
    audit = client.get(accepted["audit_url"]).json()
    assert "Malerarbeiten" in audit["chunks"][0]["source"]
    assert audit["model"] == "gemini-3.8-flash"


def test_data_download_is_only_extracted_fields_without_reasoning(setup_api, monkeypatch):
    from app.llm.extraction import ExtractedRequirements
    client, _, generate = setup_api
    def forbidden(*args, **kwargs):
        pytest.fail("Extraction must not invoke suitability reasoning")
    monkeypatch.setattr("app.llm.reasoning.analyze", forbidden)
    accepted = upload(client).json()
    job = finished(client, accepted["status_url"])
    response = client.get(accepted["data_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"] == 'attachment; filename="tender-data.json"'
    assert response.json() == job["result"]["fields"]
    assert set(response.json()) == set(ExtractedRequirements.model_fields)
    assert response.json()["estimated_value_eur"] is None
    assert "verdict" not in response.json() and "criteria" not in response.json()
    assert generate.calls == 2  # title selection + extraction; no suitability call


def test_terminal_failure_and_retry(setup_api):
    client, _, generate = setup_api
    generate.fail = True
    accepted = upload(client).json()
    job = finished(client, accepted["status_url"])
    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"]["code"] == "extraction_failed"
    assert generate.calls == 3  # selection + two invalid extraction attempts
    assert client.get(accepted["audit_url"]).status_code == 409
    assert client.get(accepted["data_url"]).status_code == 409


def test_poll_while_running_and_capacity(setup_api):
    client, _, generate = setup_api
    generate.block = True
    accepted = upload(client).json()
    assert generate.started.wait(2)
    assert client.get(accepted["status_url"]).json()["status"] == "selecting"
    assert client.get(accepted["audit_url"]).status_code == 409
    assert client.get(accepted["data_url"]).status_code == 409
    second = upload(client)
    assert second.status_code == 429
    assert second.headers["retry-after"] == "10"
    assert client.get("/health").json() == {"status": "ok"}
    generate.release.set()
    assert finished(client, accepted["status_url"])["status"] == "completed"


def test_bad_upload_and_missing_job(setup_api, monkeypatch):
    client, _, _ = setup_api
    assert client.post("/api/extractions", files={"file": ("x.pdf", b"x")}).status_code == 415
    assert client.post("/api/extractions", files={"file": ("x.zip", b"bad")}).status_code == 422
    monkeypatch.setattr("app.api.extractions.MAX_UPLOAD_BYTES", 5)
    assert upload(client).status_code == 413
    assert client.get("/api/extractions/missing").status_code == 404
    assert client.get("/api/extractions/missing/data").status_code == 404


def test_missing_configuration(setup_api, monkeypatch):
    client, _, _ = setup_api
    del app.dependency_overrides[get_generator]
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "not_configured"


def test_cors_and_openapi(setup_api):
    client, _, _ = setup_api
    response = client.options("/api/extractions", headers={
        "Origin": "http://localhost:4200", "Access-Control-Request-Method": "POST"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:4200"
    schema = client.get("/openapi.json").json()
    assert "/api/extractions" in schema["paths"]
    assert "/api/extractions/{job_id}/data" in schema["paths"]
    assert "either" not in json.dumps(schema["components"]["schemas"]["ExtractedRequirements"])


def test_upload_cleanup_and_expiry(setup_api, tmp_path, monkeypatch):
    from tempfile import NamedTemporaryFile
    client, jobs, _ = setup_api
    monkeypatch.setattr("app.api.extractions.NamedTemporaryFile",
                        lambda **kwargs: NamedTemporaryFile(dir=tmp_path, **kwargs))
    accepted = upload(client).json()
    assert finished(client, accepted["status_url"])["status"] == "completed"
    jobs.close()
    assert list(tmp_path.iterdir()) == []
    jobs.ttl_seconds = -1
    assert client.get(accepted["status_url"]).status_code == 404
    assert client.get(accepted["audit_url"]).status_code == 404
    assert client.get(accepted["data_url"]).status_code == 404


def test_api_reports_confirmed_blank_pages(setup_api):
    from tests.test_pdf_reader import text_and_blank_pdf
    client, _, _ = setup_api
    payload = io.BytesIO()
    with ZipFile(payload, 'w') as z:
        z.writestr('LV.pdf', text_and_blank_pdf())
        z.writestr('Datenschutz.pdf', b'not opened')
    accepted = client.post('/api/extractions', files={'file': ('blank.zip', payload.getvalue())}).json()
    job = finished(client, accepted['status_url'])
    assert job['status'] == 'completed', job
    assert job['result']['pages_processed'] == 2
    assert job['result']['skipped_pages'] == [{'file': 'LV.pdf', 'page': 2, 'reason': 'confirmed_blank'}]
    audit = client.get(accepted['audit_url']).json()
    assert audit['skipped_pages'] == job['result']['skipped_pages']
    assert audit['chunks'][0]['source_pages'] == [1, 3]


def test_result_contract_exposes_unverified_aggregation():
    from app.api.extraction_models import make_result
    from app.llm.extraction import merge_chunks
    chunks = [dict(file='LV.pdf', page=i, source_pages=[i], source='text',
                   fields=empty() | {'references_required': value}) for i, value in enumerate([
        'Keine Referenzen erforderlich.', 'Drei Referenzen zwingend erforderlich.',
    ], 1)]
    fields, audit = merge_chunks(chunks, 2)
    result = make_result(fields, audit, {'pdfs': [], 'ignored_non_pdf': []})
    assert result.field_status['references_required'] == 'needs_review'
    assert result.requires_review
    assert 'references_required' in result.review_reasons
    assert len(result.evidence['references_required']) == 2
