"""Bounded, in-process jobs for the single-worker demo API."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import uuid4

import requests

from app.api.extraction_models import ExtractionJob, JobError, Progress, make_result
from app.llm.extraction import ExtractionError, extract_pages
from app.llm.tender_zip import read_selected_pages, select_titles


class CapacityError(RuntimeError):
    pass


class ExtractionJobs:
    def __init__(self, workers=2, max_results=20, ttl_seconds=3600):
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="extraction")
        self.slots = BoundedSemaphore(workers)
        self.lock = Lock()
        self.jobs = {}
        self.audits = {}
        self.finished = {}
        self.max_results = max_results
        self.ttl_seconds = ttl_seconds

    def _prune(self):
        for job_id, ended in list(self.finished.items()):
            if monotonic() - ended > self.ttl_seconds:
                self.jobs.pop(job_id, None)
                self.audits.pop(job_id, None)
                del self.finished[job_id]

    def submit(self, path, filename, model, generate, inventory):
        if not self.slots.acquire(blocking=False):
            raise CapacityError("Both extraction workers are busy; retry later")
        job_id = str(uuid4())
        try:
            with self.lock:
                self._prune()
                if len(self.jobs) >= self.max_results:
                    raise CapacityError("Extraction result storage is full; retry after results expire")
                self.jobs[job_id] = ExtractionJob(id=job_id, filename=filename, model=model)
            self.pool.submit(self._run, job_id, path, generate, inventory)
        except Exception:
            with self.lock:
                self.jobs.pop(job_id, None)
            self.slots.release()
            raise
        return job_id

    def get(self, job_id):
        with self.lock:
            self._prune()
            job = self.jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def audit(self, job_id):
        with self.lock:
            return self.audits.get(job_id)

    def _update(self, job_id, **changes):
        with self.lock:
            for key, value in changes.items():
                setattr(self.jobs[job_id], key, value)

    def _run(self, job_id, path, generate, inventory):
        try:
            self._update(job_id, status="selecting")
            selection = select_titles(inventory, generate)
            self._update(job_id, status="reading")
            pages = read_selected_pages(path, selection)
            self._update(job_id, status="extracting")
            def progress(done, total):
                self._update(job_id, progress=Progress(completed_chunks=done, total_chunks=total))
            fields, audit = extract_pages(pages, generate, pack_pages=True, progress=progress)
            audit["selection"] = selection
            audit["skipped_pages"] = selection["skipped_pages"]
            audit["coverage"] = "All pages of selected PDFs only"
            audit["model"] = self.jobs[job_id].model
            result = make_result(fields, audit, selection)
            with self.lock:
                self.audits[job_id] = audit
                self.jobs[job_id].result = result
                self.jobs[job_id].status = "completed"
        except requests.RequestException:
            self._update(job_id, status="failed", error=JobError(
                code="gemini_connection_error", message="Gemini could not be reached or timed out. Please retry."))
        except ExtractionError as exc:
            # Error messages here contain no raw model output; GeminiClient redacts its API key.
            self._update(job_id, status="failed", error=JobError(code="extraction_failed", message=str(exc)))
        except Exception:
            self._update(job_id, status="failed", error=JobError(
                code="processing_failed", message="The tender could not be processed. Check that selected PDFs are readable."))
        finally:
            try:
                Path(path).unlink(missing_ok=True)
            finally:
                with self.lock:
                    self.finished[job_id] = monotonic()
                self.slots.release()

    def close(self):
        self.pool.shutdown(wait=True)
