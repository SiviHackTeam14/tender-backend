"""Serve the Story 0.3 company-profile fixtures (Story 3.2)."""
from pathlib import Path

from fastapi import APIRouter
from pydantic import TypeAdapter

from app.models import CompanyProfile

router = APIRouter(prefix="/api/profiles", tags=["profiles"])
DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "profiles.json"
_ADAPTER = TypeAdapter(list[CompanyProfile])


def load_profiles() -> list[CompanyProfile]:
    return _ADAPTER.validate_json(DATA_PATH.read_text(encoding="utf-8"))


@router.get("", response_model=list[CompanyProfile])
def get_profiles():
    return load_profiles()
