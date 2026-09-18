"""Read PDF page text plus AcroForm widgets, retaining page-local context."""
import json

from pdfminer.pdftypes import resolve1
from pdfminer.psparser import PSLiteral
from pdfminer.utils import decode_text

from app.llm.extraction import ExtractionError


def pdf_value(value):
    """Decode PDF strings (including PDFDocEncoding and UTF-16), names and arrays."""
    value = resolve1(value)
    if isinstance(value, bytes):
        return decode_text(value)
    if isinstance(value, PSLiteral):
        return value.name
    if isinstance(value, (list, tuple)):
        return [pdf_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def widget_fields(page):
    """Use raw annotations: pdfplumber's annotation decoder rejects some real VHB strings."""
    fields = []
    for annotation in resolve1(page.page_obj.attrs.get("Annots", [])):
        widget = resolve1(annotation)
        if pdf_value(widget.get("Subtype")) != "Widget":
            continue
        inherited = {}
        names = []
        current = widget
        visited = set()
        while isinstance(current, dict) and id(current) not in visited:
            visited.add(id(current))
            for key in ("FT", "V", "TU", "Ff"):
                if key in current and key not in inherited:
                    inherited[key] = current[key]
            if current.get("T") is not None:
                names.insert(0, pdf_value(current["T"]))
            current = resolve1(current.get("Parent"))
        kind = pdf_value(inherited.get("FT"))
        if kind == "Sig":
            continue  # Do not serialize signature dictionaries/certificates as tender text.
        value = pdf_value(inherited.get("V"))
        field = {"name": ".".join(names), "type": kind, "value": value,
                 "label": pdf_value(inherited.get("TU"))}
        if kind == "Btn":
            state = pdf_value(widget.get("AS"))
            field["appearance_state"] = state
            # A radio group's V is shared; AS describes this particular widget.
            field["selected"] = (state != "Off") if state is not None else None
            if state is None:
                normal = resolve1(resolve1(widget.get("AP", {})).get("N", {}))
                if isinstance(normal, dict) and value is not None:
                    options = {pdf_value(key) for key in normal} - {"Off"}
                    field["selected"] = value in options if options else None
        rect = resolve1(widget.get("Rect"))
        if rect and len(rect) == 4:
            field["rect"] = [float(n) for n in rect]
            # The nearby printed label disambiguates opaque form-field names.
            _, page_top, _, page_bottom = page.bbox
            top = max(page_top, page.height - max(rect[1], rect[3]) - 6)
            bottom = min(page_bottom, page.height - min(rect[1], rect[3]) + 6)
            if top < bottom and not page.rotation:
                field["nearby_text"] = (page.crop((page.bbox[0], top, page.bbox[2], bottom))
                                        .extract_text() or "")
        fields.append(field)
    return fields


def confirmed_blank(page):
    """Skip only demonstrably empty pages; images/drawings/annotations need OCR or review."""
    if resolve1(page.page_obj.attrs.get("Annots", [])):
        return False
    for kind, objects in page.objects.items():
        if kind == "char":
            if any(obj.get("text", "").strip() for obj in objects):
                return False
        elif objects:
            return False
    return True


def read_pdf_pages(pdf, filename, skipped_pages):
    if not pdf.pages:
        raise ExtractionError(f"Selected PDF has no pages: {filename}")
    pages = []
    for number, page in enumerate(pdf.pages, 1):
        text = page.extract_text() or ""
        fields = widget_fields(page)
        if fields:
            text += "\n[PDF_FORM_FIELDS: current widget values and selection states]\n"
            text += json.dumps(fields, ensure_ascii=False)
        if not text.strip():
            if confirmed_blank(page):
                skipped_pages.append({"file": filename, "page": number, "reason": "confirmed_blank"})
                continue
            raise ExtractionError(f"No usable text: {filename}, page {number}; OCR required")
        pages.append((filename, number, text))
    return pages
