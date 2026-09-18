"""GAEB-first-else-PDF orchestrator for one downloaded tender package (Story 1.2).

Glues together, in the parse order the epic specifies (GAEB -> pdfplumber ->
Gemini Vision last):

1. ``app.llm.tender_zip.find_gaeb_member`` / ``app.llm.gaeb.parse_gaeb`` — free,
   no LLM call, skipped entirely if no GAEB member exists.
2. The existing Story 2.1 flow, unmodified: ``tender_zip.inventory_zip`` ->
   ``tender_zip.select_titles`` (Gemini title-selection) ->
   ``tender_zip.read_selected_pages_with_ocr_fallback`` (pdfplumber text, with
   ``app.llm.vision_ocr`` as the last-resort per-page fallback).

``zip_bytes`` may be a real downloaded ZIP (cosinex adapter) or an in-memory ZIP
synthesized from individually downloaded files (RIB adapter) — both are valid
input to ``zipfile.ZipFile`` and therefore to every function called here.
"""
from __future__ import annotations

import io

from app.llm import gaeb, tender_zip
from app.llm.extraction import ExtractionError

ExtractionMethod = str  # "gaeb" | "pdf_text" | "pdf_vision"


def load_pages(
    zip_bytes: bytes,
    generate,
    vision_generate=None,
) -> tuple[list[tuple[str, int, str]], ExtractionMethod, dict]:
    """Return ``(pages, extraction_method, meta)`` for one package.

    ``extraction_method`` is ``"gaeb"`` if a GAEB member drove the result,
    ``"pdf_text"`` if every page came from ``pdfplumber``'s text layer, or
    ``"pdf_vision"`` if at least one page needed the Vision OCR fallback.
    ``meta`` carries observability fields (``gaeb_member``, ``ocr_pages_used``,
    ``ocr_pages_dropped``) that ``scripts/enrich_notices.py`` folds into its
    per-notice log line.
    """
    buffer = io.BytesIO(zip_bytes)

    gaeb_member = tender_zip.find_gaeb_member(buffer)
    if gaeb_member is not None:
        with io.BytesIO(zip_bytes) as z:
            import zipfile

            with zipfile.ZipFile(z) as archive:
                xml_bytes = archive.read(gaeb_member)
        try:
            pages = gaeb.parse_gaeb(xml_bytes, gaeb_member)
            return pages, "gaeb", {"gaeb_member": gaeb_member}
        except ExtractionError:
            # Unparsable GAEB with a usable PDF alongside it -> fall through
            # to the PDF path below instead of failing the whole notice.
            pass

    inventory = tender_zip.inventory_zip(buffer)
    report = tender_zip.select_titles(inventory, generate)

    def ocr_page(pdf_bytes, entry_path, page_number):
        if vision_generate is None:
            return ""
        from app.llm.vision_ocr import ocr_page as _ocr_page

        return _ocr_page(pdf_bytes, entry_path, page_number, vision_generate)

    pages, ocr_used, ocr_dropped = tender_zip.read_selected_pages_with_ocr_fallback(
        buffer, report, ocr_page=ocr_page
    )
    method = "pdf_vision" if ocr_used else "pdf_text"
    meta = {"gaeb_member": gaeb_member, "ocr_pages_used": ocr_used, "ocr_pages_dropped": ocr_dropped}
    return pages, method, meta
