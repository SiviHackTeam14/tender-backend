"""Upload a tender ZIP, then poll its extraction job."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile

from app.api.extraction_models import ExtractionJob, JobAccepted
from app.llm.extraction import ExtractionError, GeminiClient
from app.llm.tender_zip import inventory_zip
from app.services.extraction_jobs import CapacityError, ExtractionJobs

router = APIRouter(prefix="/api/extractions", tags=["extractions"])
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def get_jobs(request: Request) -> ExtractionJobs:
    return request.app.state.extraction_jobs


def get_generator():
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    try:
        return GeminiClient(os.getenv("GEMINI_API_KEY", ""), model)
    except ValueError:
        raise HTTPException(503, detail={"code": "not_configured", "message": "Configure GEMINI_API_KEY and GEMINI_MODEL on the backend"})


@router.post("", response_model=JobAccepted, status_code=202)
def create_extraction(file: UploadFile, response: Response,
                      jobs: ExtractionJobs = Depends(get_jobs), generate=Depends(get_generator)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(415, detail={"code": "unsupported_file", "message": "Upload one tender ZIP"})
    path = None
    owned_by_job = False
    try:
        with NamedTemporaryFile(suffix=".zip", delete=False) as target:
            path = Path(target.name)
            size = 0
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, detail={"code": "upload_too_large", "message": "Maximum ZIP size is 50 MiB"})
                target.write(chunk)
        try:
            inventory = inventory_zip(path)
        except (BadZipFile, ExtractionError) as exc:
            raise HTTPException(422, detail={"code": "invalid_archive", "message": str(exc)})
        pdfs = inventory["pdfs"]
        if len(pdfs) > 200 or sum(item["bytes"] for item in pdfs) > 250 * 1024 * 1024:
            raise HTTPException(413, detail={"code": "archive_too_large", "message": "Maximum 200 PDFs and 250 MiB of uncompressed PDF data"})
        try:
            job_id = jobs.submit(path, Path(file.filename.replace("\\", "/")).name,
                                 generate.model, generate, inventory)
        except CapacityError as exc:
            raise HTTPException(429, detail={"code": "busy", "message": str(exc)}, headers={"Retry-After": "10"})
        owned_by_job = True
        url = f"/api/extractions/{job_id}"
        response.headers["Location"] = url
        return JobAccepted(id=job_id, status_url=url, audit_url=url + "/audit")
    finally:
        file.file.close()
        if path and not owned_by_job:
            path.unlink(missing_ok=True)


@router.get("/{job_id}", response_model=ExtractionJob)
def get_extraction(job_id: str, jobs: ExtractionJobs = Depends(get_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Job not found or expired"})
    return job


@router.get("/{job_id}/audit")
def get_audit(job_id: str, jobs: ExtractionJobs = Depends(get_jobs)):
    job = get_extraction(job_id, jobs)
    if job.status != "completed":
        raise HTTPException(409, detail={"code": "not_ready", "message": "Audit is available after successful extraction"})
    return jobs.audit(job_id)
