import io
import json
from pathlib import Path
from zipfile import ZipFile

import pdfplumber
import pytest

from app.llm.extraction import ExtractionError
from app.llm.pdf_reader import read_pdf_pages
from app.llm.tender_zip import inventory_zip, read_selected_pages
from scripts.extract_tender import read_pages


def make_pdf(objects):
    data = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return data + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def stream(content):
    return b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"


def text_and_blank_pdf(scanned=False):
    content = b"BT /F1 12 Tf 50 750 Td (Malerarbeiten) Tj ET"
    return make_pdf([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 6 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /XObject << /Im0 9 0 R >> >> /Contents 8 0 R >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 6 0 R >> >> /Contents 7 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream(content),
        stream(b"q 100 0 0 100 50 50 cm /Im0 Do Q" if scanned else b""),
        b"<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 /Length 1 >>\nstream\n\x00\nendstream",
    ])


def form_pdf():
    label = (b"\xfe\xff" + "Ausführungsbeginn".encode("utf-16-be")).hex().encode()
    return make_pdf([
        b"<< /Type /Catalog /Pages 2 0 R /AcroForm 6 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R /Annots [7 0 R 8 0 R 9 0 R 10 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream(b"BT /F1 12 Tf 50 750 Td (Baubeginn:) Tj ET"),
        b"<< /Fields [11 0 R 8 0 R 12 0 R] >>",
        b"<< /Type /Annot /Subtype /Widget /Parent 11 0 R /Rect [150 740 250 760] /P 3 0 R >>",
        b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (Sicherheit) /V /Yes /AS /Yes /Rect [50 690 60 700] /P 3 0 R >>",
        b"<< /Type /Annot /Subtype /Widget /Parent 12 0 R /AS /ChoiceA /Rect [50 650 60 660] /P 3 0 R >>",
        b"<< /Type /Annot /Subtype /Widget /Parent 12 0 R /AS /Off /Rect [50 610 60 620] /P 3 0 R >>",
        b"<< /FT /Tx /T (construction_start) /TU <" + label + b"> /V (23.11.2026) /Kids [7 0 R] >>",
        b"<< /FT /Btn /Ff 32768 /T (Rolle) /V /ChoiceA /Kids [9 0 R 10 0 R] >>",
    ])


def test_inherited_form_values_and_individual_radio_states():
    with pdfplumber.open(io.BytesIO(form_pdf())) as pdf:
        assert "23.11.2026" not in pdf.pages[0].extract_text()
        pages = read_pdf_pages(pdf, "form.pdf", [])
    fields = json.loads(pages[0][2].split("selection states]\n")[1])
    assert fields[0]["value"] == "23.11.2026"
    assert fields[0]["name"] == "construction_start"
    assert fields[0]["label"] == "Ausführungsbeginn"
    assert "Baubeginn" in fields[0]["nearby_text"]
    assert fields[1]["selected"] is True
    assert [field["selected"] for field in fields if field["name"] == "Rolle"] == [True, False]


def test_blank_page_skipped_without_renumbering(tmp_path):
    file = tmp_path / "tender.pdf"
    file.write_bytes(text_and_blank_pdf())
    skipped = []
    pages = read_pages(file, skipped)
    assert [page for _, page, _ in pages] == [1, 3]
    assert skipped == [{"file": str(file), "page": 2, "reason": "confirmed_blank"}]


def test_zip_reader_records_skipped_page(tmp_path):
    file = tmp_path / "tender.zip"
    with ZipFile(file, "w") as archive:
        archive.writestr("LV.pdf", text_and_blank_pdf())
    report = inventory_zip(file)
    report["pdfs"][0]["decision"] = "include"
    pages = read_selected_pages(file, report)
    assert [page for _, page, _ in pages] == [1, 3]
    assert report["skipped_pages"] == [{"file": "LV.pdf", "page": 2, "reason": "confirmed_blank"}]


def test_image_page_is_not_silently_skipped():
    with pdfplumber.open(io.BytesIO(text_and_blank_pdf(scanned=True))) as pdf:
        with pytest.raises(ExtractionError, match="page 2; OCR required"):
            read_pdf_pages(pdf, "scan.pdf", [])


REAL_TENDER = Path(__file__).resolve().parents[1] / "app/llm/2.653.880_Ausschreibungsunterlagen.zip"


@pytest.mark.skipif(not REAL_TENDER.exists(), reason="Real tender ZIP is a local fixture")
def test_real_tender_filled_dates_reach_extraction():
    from app.llm.extraction import extract_pages
    from tests.test_extraction import empty
    name = "Vergabeunterlagen/Bewerbungsbedingungen/214_Besondere Vertragsbedingungen.pdf"
    with ZipFile(REAL_TENDER) as archive:
        with pdfplumber.open(io.BytesIO(archive.read(name))) as pdf:
            pages = read_pdf_pages(pdf, name, [])
    prompts = []
    def generate(prompt, schema):
        prompts.append(prompt)
        return json.dumps(empty())
    extract_pages(pages, generate, pack_pages=True)
    assert any('"name": "ag_214_beginn_datum"' in p and '"value": "23.11.2026"' in p for p in prompts)
    assert any('"name": "ag_214_ende_datum"' in p and '"value": "18.12.2026"' in p for p in prompts)
    assert any('"selected": true' in p for p in prompts)
