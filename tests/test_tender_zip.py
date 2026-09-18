import json
from zipfile import ZipFile

import pytest

from app.llm.extraction import ExtractionError
from app.llm.tender_zip import inventory_zip, read_selected_pages, select_titles


def package(tmp_path):
    path = tmp_path / "tender.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("docs/01_LV.PDF", b"selected")
        archive.writestr("docs/Datenschutz.pdf", b"excluded")
        archive.writestr("other.x83", b"not a PDF")
    return path


def decisions():
    return {"documents": [
        {"id": 0, "decision": "include", "relevant_fields": ["trade_type"], "reason": "Leistungsverzeichnis"},
        {"id": 1, "decision": "exclude", "relevant_fields": [], "reason": "Datenschutz"},
    ]}


def test_inventory_and_selection_do_not_open_pdfs(tmp_path, monkeypatch):
    path = package(tmp_path)
    def fail(*args):
        raise AssertionError("PDF content opened during title selection")
    monkeypatch.setattr(ZipFile, "read", fail)
    inventory = inventory_zip(path)
    assert len(inventory["pdfs"]) == 2
    assert inventory["ignored_non_pdf"] == ["other.x83"]
    def generate(prompt, schema):
        assert "01_LV" in prompt and "Datenschutz" in prompt
        return json.dumps(decisions())
    report = select_titles(inventory, generate)
    assert report["pdfs"][0]["decision"] == "include"


def test_only_selected_pdf_is_read(tmp_path, monkeypatch):
    import pdfplumber
    path = package(tmp_path)
    report = select_titles(inventory_zip(path), lambda *args: json.dumps(decisions()))
    opened = []
    class Page:
        def extract_text(self):
            return "LV text"
    class PDF:
        pages = [Page()]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    def open_pdf(stream):
        opened.append(stream.read())
        return PDF()
    monkeypatch.setattr(pdfplumber, "open", open_pdf)
    assert read_selected_pages(path, report) == [("docs/01_LV.PDF", 1, "LV text")]
    assert opened == [b"selected"]


@pytest.mark.parametrize("bad", [
    {"documents": []},
    {"documents": [decisions()["documents"][0]] * 2},
    {"documents": [decisions()["documents"][0] | {"relevant_fields": ["invented"]}, decisions()["documents"][1]]},
])
def test_bad_selection_retried_once(tmp_path, bad):
    calls = []
    def generate(*args):
        calls.append(1)
        return json.dumps(bad)
    with pytest.raises(ExtractionError, match="two attempts"):
        select_titles(inventory_zip(package(tmp_path)), generate)
    assert len(calls) == 2


def test_selection_retry_can_recover(tmp_path):
    responses = iter(["not JSON", json.dumps(decisions())])
    result = select_titles(inventory_zip(package(tmp_path)), lambda *args: next(responses))
    assert result["pdfs"][0]["decision"] == "include"


def test_no_selected_documents_fails(tmp_path):
    report = inventory_zip(package(tmp_path))
    for entry in report["pdfs"]:
        entry["decision"] = "exclude"
    with pytest.raises(ExtractionError, match="No PDF titles selected"):
        read_selected_pages(tmp_path / "tender.zip", report)
