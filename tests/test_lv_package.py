import io
import json
import zipfile
from pathlib import Path

import pytest

from app.llm.lv_package import load_pages
from app.llm.tender_zip import find_gaeb_member, inventory_zip

FIXTURE_ZIP = Path(__file__).resolve().parent / "fixtures" / "rolandbrunnen-sample.zip"


def _zip_bytes_without_gaeb() -> bytes:
    """A copy of the fixture with the GAEB member stripped, so the PDF
    fallback path can be exercised deterministically."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(FIXTURE_ZIP) as src, zipfile.ZipFile(buffer, "w") as dst:
        for name in src.namelist():
            if find_gaeb_member(FIXTURE_ZIP) == name:
                continue
            dst.writestr(name, src.read(name))
    return buffer.getvalue()


def _title_selection_generate(zip_bytes: bytes):
    """A fake ``generate`` that includes only the LV-titled PDF, matching the
    real Story 2.1 TitleSelection JSON schema."""
    inventory = inventory_zip(io.BytesIO(zip_bytes))

    def generate(prompt, schema):
        decisions = [
            {
                "id": entry["id"],
                "decision": "include" if "LV_2026" in entry["title"] else "exclude",
                "relevant_fields": ["trade_type"] if "LV_2026" in entry["title"] else [],
                "reason": "test fixture",
            }
            for entry in inventory["pdfs"]
        ]
        return json.dumps({"documents": decisions})

    return generate


def test_load_pages_gaeb_present_never_calls_generate():
    zip_bytes = FIXTURE_ZIP.read_bytes()

    def boom(*args, **kwargs):
        raise AssertionError("generate() called even though a GAEB member exists")

    pages, method, meta = load_pages(zip_bytes, boom)
    assert method == "gaeb"
    assert meta["gaeb_member"] == "LV_20260904_Nordhausen_Rolandbrunnen.x83"
    assert pages
    assert all(isinstance(page[1], int) for page in pages)


def test_load_pages_falls_back_to_pdf_when_no_gaeb():
    zip_bytes = _zip_bytes_without_gaeb()
    generate = _title_selection_generate(zip_bytes)

    pages, method, meta = load_pages(zip_bytes, generate)
    assert method == "pdf_text"
    assert meta["gaeb_member"] is None
    assert meta["ocr_pages_used"] == 0
    assert pages
    # Only the included (LV-titled) PDF's pages should be present.
    assert all("LV_2026" in filename for filename, _, _ in pages)


def test_load_pages_pdf_vision_fallback_used_when_page_has_no_text(monkeypatch):
    """A selected PDF page with no text layer should fall through to the
    Vision OCR callback (mocked here), producing method="pdf_vision"."""
    import pdfplumber

    zip_bytes = _zip_bytes_without_gaeb()
    generate = _title_selection_generate(zip_bytes)

    original_extract_text = pdfplumber.page.Page.extract_text
    call_count = {"n": 0}

    def blank_first_page(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ""
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "extract_text", blank_first_page)

    def fake_vision_generate(png_bytes: bytes) -> str:
        assert png_bytes  # a real PNG was rendered
        return "OCR-transcribed page text"

    pages, method, meta = load_pages(zip_bytes, generate, fake_vision_generate)
    assert method == "pdf_vision"
    assert meta["ocr_pages_used"] == 1
    assert any(text == "OCR-transcribed page text" for _, _, text in pages)


def test_load_pages_drops_ocr_page_when_no_vision_generate(monkeypatch):
    import pdfplumber

    zip_bytes = _zip_bytes_without_gaeb()
    generate = _title_selection_generate(zip_bytes)

    call_count = {"n": 0}
    original_extract_text = pdfplumber.page.Page.extract_text

    def blank_first_page(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return ""
        return original_extract_text(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "extract_text", blank_first_page)

    pages, method, meta = load_pages(zip_bytes, generate, vision_generate=None)
    assert method == "pdf_text"  # no OCR call happened, so still plain text
    assert meta["ocr_pages_dropped"] == 1
