import zipfile
from pathlib import Path

import pytest

from app.llm.extraction import ExtractionError
from app.llm.gaeb import is_gaeb_member, parse_gaeb

FIXTURE_ZIP = Path(__file__).resolve().parent / "fixtures" / "rolandbrunnen-sample.zip"
GAEB_MEMBER = "LV_20260904_Nordhausen_Rolandbrunnen.x83"


@pytest.fixture()
def gaeb_bytes() -> bytes:
    with zipfile.ZipFile(FIXTURE_ZIP) as z:
        return z.read(GAEB_MEMBER)


def test_is_gaeb_member():
    assert is_gaeb_member("LV.x83")
    assert is_gaeb_member("lv.X81")
    assert is_gaeb_member("lv.x84")
    assert not is_gaeb_member("LV.pdf")
    assert not is_gaeb_member("Datenschutz.pdf")


def test_parse_gaeb_returns_nonempty_pages(gaeb_bytes):
    pages = parse_gaeb(gaeb_bytes, GAEB_MEMBER)
    assert pages
    for filename, page_number, text in pages:
        assert filename == GAEB_MEMBER
        assert isinstance(page_number, int)
        assert text.strip()


def test_parse_gaeb_page_numbers_are_sequential(gaeb_bytes):
    pages = parse_gaeb(gaeb_bytes, GAEB_MEMBER)
    assert [p for _, p, _ in pages] == list(range(1, len(pages) + 1))


def test_parse_gaeb_finds_real_contract_clauses(gaeb_bytes):
    """Real strings verified present in the live sample file — AddText blocks
    (free-text clauses), not only bill-of-quantities line items, must reach
    the joined text or the most relevant sentences never reach extract_pages."""
    pages = parse_gaeb(gaeb_bytes, GAEB_MEMBER)
    full_text = "\n".join(text for _, _, text in pages)
    assert "Gewerkekoordination" in full_text
    assert "Wassertechnik" in full_text


def test_parse_gaeb_addtext_pages_come_before_itemlist_pages(gaeb_bytes):
    """AddText blocks are emitted first so they survive the caller's
    MAX_LV_PAGES cap."""
    pages = parse_gaeb(gaeb_bytes, GAEB_MEMBER)
    first_text = pages[0][2]
    assert "Gewerkekoordination" in first_text


def test_parse_gaeb_raises_on_empty_document():
    empty_gaeb = (
        b'<?xml version="1.0" encoding="utf-8"?>'
        b'<GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.2">'
        b"<GAEBInfo><Version>3.2</Version></GAEBInfo>"
        b"</GAEB>"
    )
    with pytest.raises(ExtractionError, match="No GAEB text found"):
        parse_gaeb(empty_gaeb, "empty.x83")


def test_parse_gaeb_raises_on_malformed_xml():
    with pytest.raises(ExtractionError, match="not well-formed"):
        parse_gaeb(b"<GAEB><unterminated>", "broken.x83")
