"""GAEB DA XML (.x83/.x81/.x84) -> pages, parsed for free (no LLM call).

GAEB is the German construction industry's structured exchange format for a
Leistungsverzeichnis (LV). When a tender package contains one, it *is* the LV
by construction — no Gemini title-selection guessing is needed, unlike the PDF
path in ``app.llm.tender_zip``.

Verified against the real sample
(``33_61_2026_Ausschreibungsunterlagen/Vergabeunterlagen/LV_20260904_Nordhausen_Rolandbrunnen.x83``,
GAEB DA XML 3.2, namespace ``http://www.gaeb.de/GAEB_DA_XML/DA83/3.2``). This
parser strips the namespace by local tag name so it tolerates DA81/DA84's
different namespace URIs without needing to enumerate them.

Two kinds of pseudo-page are produced, in document order:

1. ``Award/AddText`` blocks (``OutlineAddText`` + ``DetailAddText``) — the free-text
   contract clauses. Verified live: one real block's heading is literally
   "Gewerkekoordination" and another requires an "erfahrenen
   Wassertechnik-Fachbetrieb" — exactly the kind of sentence the semantic
   extraction step (``app.llm.extraction.extract_pages``) needs to see. These are
   emitted *first* so they survive the caller's ``MAX_LV_PAGES`` cap.
2. One pseudo-page per ``Itemlist`` (bill-of-quantities section), concatenating
   every ``Item``'s quantity/unit and description text. Grouping by ``Itemlist``
   (not by individual ``Item``) keeps the page count bounded by the number of LV
   sections rather than the number of line items, which can run into the
   hundreds.

Real GAEB pages have no page numbers; the second tuple element is simply a
1-based sequence over these pseudo-pages, matching the
``(filename, page, text)`` contract ``extract_pages`` expects from any source.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from app.llm.extraction import ExtractionError

GAEB_EXTENSIONS = (".x83", ".x81", ".x84")


def is_gaeb_member(filename: str) -> bool:
    return filename.lower().endswith(GAEB_EXTENSIONS)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _paragraph_text(p_element: ET.Element) -> str:
    """Concatenate every ``span`` descendant's text within one ``<p>``."""
    parts = [span.text for span in p_element.iter() if _local(span.tag) == "span" and span.text]
    if not parts and p_element.text:
        parts = [p_element.text]
    return "".join(parts).strip()


def _collect_paragraphs(element: ET.Element) -> str:
    """Join every ``<p>`` found anywhere under ``element``, one per line."""
    lines = [
        text
        for child in element.iter()
        if _local(child.tag) == "p" and (text := _paragraph_text(child))
    ]
    return "\n".join(lines)


def _add_text_pages(root: ET.Element) -> list[str]:
    pages = []
    for add_text in root.iter():
        if _local(add_text.tag) != "AddText":
            continue
        heading = detail = ""
        for child in add_text:
            local = _local(child.tag)
            if local == "OutlineAddText":
                heading = _collect_paragraphs(child)
            elif local == "DetailAddText":
                detail = _collect_paragraphs(child)
        text = "\n".join(part for part in (heading, detail) if part)
        if text.strip():
            pages.append(text)
    return pages


def _item_lines(itemlist: ET.Element) -> list[str]:
    lines = []
    for item in itemlist:
        if _local(item.tag) != "Item":
            continue
        position = item.get("RNoPart") or item.get("ID") or ""
        qty = qu = description = ""
        for child in item:
            local = _local(child.tag)
            if local == "Qty":
                qty = (child.text or "").strip()
            elif local == "QU":
                qu = (child.text or "").strip()
            elif local == "Description":
                description = _collect_paragraphs(child)
        if not description.strip():
            continue
        prefix = f"Pos {position}".strip() if position else "Pos"
        if qty or qu:
            prefix += f" ({qty} {qu})".rstrip()
        lines.append(f"{prefix}: {description}")
    return lines


def _itemlist_pages(root: ET.Element) -> list[str]:
    pages = []
    for itemlist in root.iter():
        if _local(itemlist.tag) != "Itemlist":
            continue
        lines = _item_lines(itemlist)
        if lines:
            pages.append("\n".join(lines))
    return pages


def parse_gaeb(xml_bytes: bytes, filename: str) -> list[tuple[str, int, str]]:
    """Parse one GAEB XML document into ``(filename, page, text)`` tuples.

    Raises ``ExtractionError`` if the walk finds no text at all — callers
    should treat this the same way a title-selection-with-zero-PDFs failure is
    treated (fall back to another source, or skip and log), never hand
    ``extract_pages`` an empty list.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise ExtractionError(f"GAEB XML is not well-formed: {exc}") from exc

    texts = _add_text_pages(root) + _itemlist_pages(root)
    if not texts:
        raise ExtractionError("No GAEB text found (no AddText or Itemlist content)")

    return [(filename, index, text) for index, text in enumerate(texts, 1)]
