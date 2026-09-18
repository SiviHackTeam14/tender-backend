"""Serve the current tender fixture set (Story 3.2)."""
from pathlib import Path

from fastapi import APIRouter
from pydantic import TypeAdapter

from app.models import Tender

router = APIRouter(prefix="/api/tenders", tags=["tenders"])
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "tenders.json"
_ADAPTER = TypeAdapter(list[Tender])


def load_tenders() -> list[Tender]:
    return _ADAPTER.validate_json(DATA_PATH.read_text(encoding="utf-8"))


@router.get("", response_model=list[Tender])
def get_tenders():
    return load_tenders()
