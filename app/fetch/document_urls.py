"""OCDS day-export fetch + join (Story 1.2).

Story 1.1 proved there is no ``GET /api/notices/{id}``: the Bekanntmachungsservice
Open Data API exposes exactly one path, ``/api/notice-exports``, which returns a
*day's* ZIP in one of several formats selected by ``Accept``/``format``. The CSV
format (Story 1.1) has no document URLs. The OCDS format
(``application/vnd.bekanntmachungsservice.ocds.zip+zip``) contains one JSON file
per notice, named ``{noticeIdentifier}-{noticeVersion}.json``, and the document
URLs live at ``releases[0]["tender"]["documents"]``.

This module re-fetches, for each distinct ``publicationDate`` day already present
in ``data/raw_notices.json``, that day's OCDS export, and looks up the document
URLs for one specific ``(noticeIdentifier, noticeVersion)`` pair.

Only ``fetch_ocds_day`` touches the network; everything else is pure and safe to
import/call from tests without mocking anything but ``requests.get``.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Optional

import requests

BASE_URL = "https://oeffentlichevergabe.de/api/notice-exports"
OCDS_ACCEPT = "application/vnd.bekanntmachungsservice.ocds.zip+zip"

# scripts/ is deliberately not a package (Story 1.1: importing it must never
# trigger network calls, and it is loaded via importlib in tests). Reuse its
# exact noticeVersion parsing rule ("01" and "1" both -> 1) instead of
# duplicating it, by adding scripts/ to sys.path once.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
from prototype import parse_version  # noqa: E402  (see path setup above)


def fetch_ocds_day(pub_day: str) -> bytes:
    """Download one day's OCDS export ZIP bytes.

    Any failure (timeout, non-200, empty body) is logged and yields ``b""`` so
    the caller can skip that day's notices without aborting the batch — same
    contract as Story 1.1's ``fetch_day``.
    """
    try:
        r = requests.get(
            BASE_URL,
            params={"pubDay": pub_day},
            headers={"Accept": OCDS_ACCEPT},
            timeout=120,
        )
    except requests.RequestException as exc:
        print(f"  {pub_day}: OCDS request failed ({exc}) — skipping")
        return b""

    if r.status_code != 200:
        print(f"  {pub_day}: OCDS HTTP {r.status_code} — skipping")
        return b""

    if not r.content:
        print(f"  {pub_day}: OCDS empty body — skipping")
        return b""

    return r.content


def index_ocds_zip(zip_bytes: bytes) -> dict[str, dict[int, str]]:
    """Parse an OCDS ZIP's member names into ``{noticeIdentifier: {version: filename}}``.

    Network-free. Raises ``zipfile.BadZipFile`` on corrupt input — the caller
    decides whether that means "skip this day" or should propagate.
    """
    index: dict[str, dict[int, str]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            base = name[: -len(".json")]
            notice_id, _, version_raw = base.rpartition("-")
            if not notice_id:
                continue
            index.setdefault(notice_id, {})[parse_version(version_raw)] = name
    return index


def extract_document_urls(zip_bytes: bytes, filename: str) -> list[dict]:
    """Read one OCDS entry and return its ``tender.documents`` list verbatim.

    Network-free. Returns ``[]`` if the release has no documents at all — the
    common case (most real notices have none).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        release_package = json.loads(z.read(filename))
    releases = release_package.get("releases") or []
    if not releases:
        return []
    tender = releases[0].get("tender") or {}
    return tender.get("documents") or []


def get_document_urls_for_notice(
    zip_bytes: bytes,
    notice_identifier: str,
    notice_version,
    index: Optional[dict[str, dict[int, str]]] = None,
) -> list[dict]:
    """Convenience wrapper: index (if not supplied) + look up one notice + extract.

    Returns ``[]`` if the day's export has no matching
    ``(noticeIdentifier, noticeVersion)`` entry — not an error.
    """
    if index is None:
        index = index_ocds_zip(zip_bytes)
    filename = index.get(notice_identifier, {}).get(parse_version(notice_version))
    if filename is None:
        return []
    return extract_document_urls(zip_bytes, filename)
