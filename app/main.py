from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.analyze import router as analyze_router
from app.api.extractions import router as extraction_router
from app.api.profiles import router as profiles_router
from app.api.tenders import router as tenders_router
from app.services.extraction_jobs import ExtractionJobs

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from starlette.concurrency import run_in_threadpool
    app.state.extraction_jobs = ExtractionJobs()
    try:
        yield
    finally:
        await run_in_threadpool(app.state.extraction_jobs.close)

app = FastAPI(title="tender-backend", version="0.1.0", lifespan=lifespan)
app.include_router(extraction_router)
app.include_router(profiles_router)
app.include_router(tenders_router)
app.include_router(analyze_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}
