"""Opt-in, real Gemini test. Uses API quota and sends selected PDF text to Google."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.llm.extraction import ExtractedRequirements
from app.llm.tender_zip import inventory_zip


@pytest.mark.skipif(os.getenv("RUN_GEMINI_ZIP_TEST") != "1", reason="Set RUN_GEMINI_ZIP_TEST=1 for live Gemini test")
def test_real_tender_with_gemini_38(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    source = backend / "app/llm/2.653.880_Ausschreibungsunterlagen.zip"
    assert source.exists(), f"Missing real tender fixture: {source}"
    audit_path = tmp_path / "audit.json"
    selection_path = tmp_path / "selection.json"
    run = subprocess.run([
        sys.executable, "scripts/extract_tender.py", str(source),
        "--model", "gemini-3.8-flash", "--audit", str(audit_path),
        "--selection-report", str(selection_path),
    ], cwd=backend, capture_output=True, text=True, timeout=3600)
    assert run.returncode == 0, run.stderr
    fields = ExtractedRequirements.model_validate_json(run.stdout)
    (tmp_path / "fields.json").write_text(run.stdout)
    selection = json.loads(selection_path.read_text())
    audit = json.loads(audit_path.read_text())
    all_paths = {entry["path"] for entry in inventory_zip(source)["pdfs"]}
    assert {entry["path"] for entry in selection["pdfs"]} == all_paths
    selected = {entry["path"] for entry in selection["pdfs"] if entry["decision"] == "include"}
    assert any(path.endswith("01_LV.pdf") for path in selected)
    assert {chunk["file"] for chunk in audit["chunks"]} == selected
    assert audit["complete"] and audit["model"] == "gemini-3.8-flash"
    assert fields.role_required in {None, "main_contractor", "subcontractor"}
    assert audit["pages_processed"] > 10
    # Filled form 214 supplies the start date; do not regress to page-text-only reading.
    assert (fields.construction_window_start == "2026-11-23" or
            "2026-11-23" in audit["conflicts"].get("construction_window_start", []))
    # Source-grounded check: 01_LV.pdf page 8 explicitly sets 18.12.2026.
    assert (fields.construction_window_end == "2026-12-18" or
            "2026-12-18" in audit["conflicts"].get("construction_window_end", []))
    # Form 214's EUR 250,000 is a conditional threshold, never the tender value.
    assert fields.estimated_value_eur != 250000
    print(f"Live outputs for source review: {tmp_path}")
