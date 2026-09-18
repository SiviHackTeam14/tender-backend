"""Multi-region fetch script (Story 1.1).

Downloads the last ``FETCH_DAYS_BACK`` daily CSV exports from
oeffentlichevergabe.de, joins the ``notice`` table against
``classification`` / ``placeOfPerformance`` / ``purpose`` / ``organisation`` /
``submissionTerms`` on ``(noticeIdentifier, noticeVersion)``, applies the
competition / CPV / NUTS / deadline filters locally, dedups to the latest
``noticeVersion`` per notice, caps the result at ``MAX_FETCH``, and writes the
survivors to ``data/raw_notices.json``.

Everything above the ``if __name__ == "__main__":`` guard is import-safe: no
network calls happen at module load time. Only ``main()`` (and the functions
it calls) touch the network, so tests can load this module with
``importlib`` and exercise the join/filter/dedup helpers directly.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

# ── CONFIG ────────────────────────────────────────────────────
BASE_URL = "https://oeffentlichevergabe.de/api/notice-exports"

# Server-side filters (sent as params). NOTE: the portal does not actually
# shrink the ZIP based on these — they are documentation of intent only. The
# real filtering happens locally below, after the join.
CPV_PREFIXES = ["45"]  # Construction works only
NUTS_PREFIXES = [
    "DE21", "DE27",  # Oberbayern, Schwaben (Profile A)
    "DED", "DEG",    # Saxony, Thuringia  (Profile B)
    "DE22", "DE23",  # Niederbayern, Oberpfalz (buffer)
    "DE14", "DE11",  # Tübingen, Stuttgart (southern buffer)
]
FETCH_DAYS_BACK = 21  # last 3 weeks — enough to get 40+ good tenders
MAX_FETCH = 500  # safety cap, applied after dedup, newest publicationDate first

# Local filter: only these notice types = "competition / bidding phase"
COMPETITION_NOTICE_TYPES = {
    "cn-standard",  # standard open/restricted/negotiated competition
    "cn-social",    # social services competition
    "cn-desg",      # concession competition
}

OUTPUT_KEYS = (
    "noticeIdentifier",
    "noticeVersion",
    "noticeType",
    "publicationDate",
    "title",
    "description",
    "estimatedValue",
    "cpvCodes",
    "nutsCodes",
    "location",
    "publicOpeningDate",
)

NoticeKey = tuple[Optional[str], Optional[str]]
TableIndex = dict[NoticeKey, list[dict]]


# ── STEP 0: FETCH + PARSE (network boundary) ───────────────────
def parse_zip_tables(content: bytes) -> dict[str, list[dict]]:
    """Parse a notice-export ZIP's bytes into ``{table_name: [rows]}``.

    Raises ``zipfile.BadZipFile`` on corrupt input — callers decide whether
    that means "skip this day" (fetch_day) or should propagate (tests).
    """
    tables: dict[str, list[dict]] = {}
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for name in z.namelist():
            if not name.endswith(".csv"):
                continue
            key = name.split("/")[-1].removesuffix(".csv")
            with z.open(name) as fh:
                reader = csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8"))
                tables[key] = list(reader)
    return tables


def fetch_day(pub_day: str) -> dict[str, list[dict]]:
    """Download one day's CSV ZIP and return its tables.

    Any failure (timeout, non-200, empty body, corrupt ZIP) is logged and
    yields ``{}`` so the caller's window keeps going instead of aborting.
    """
    try:
        r = requests.get(BASE_URL, params={"pubDay": pub_day, "format": "csv.zip"}, timeout=120)
    except requests.RequestException as exc:
        print(f"  {pub_day}: request failed ({exc}) — skipping")
        return {}

    if r.status_code != 200:
        print(f"  {pub_day}: HTTP {r.status_code} — skipping")
        return {}

    if not r.content:
        print(f"  {pub_day}: empty body — skipping")
        return {}

    try:
        return parse_zip_tables(r.content)
    except zipfile.BadZipFile:
        print(f"  {pub_day}: corrupt ZIP — skipping")
        return {}


def merge_tables(all_days: list[dict[str, list[dict]]]) -> dict[str, list[dict]]:
    """Concatenate same-named tables across multiple days' exports."""
    merged: dict[str, list[dict]] = {}
    for tables in all_days:
        for key, rows in tables.items():
            merged.setdefault(key, []).extend(rows)
    return merged


def fetch_all_days(days_back: int = FETCH_DAYS_BACK) -> dict[str, list[dict]]:
    """Network entry point: fetch and merge the last ``days_back`` days."""
    all_days = []
    for i in range(1, days_back + 1):
        pub_day = (date.today() - timedelta(days=i)).isoformat()
        print(f"Fetching {pub_day}...")
        all_days.append(fetch_day(pub_day))
    return merge_tables(all_days)


# ── JOIN HELPERS ────────────────────────────────────────────────
def notice_key(row: dict) -> NoticeKey:
    return (row.get("noticeIdentifier"), row.get("noticeVersion"))


def index_by_notice(rows: list[dict]) -> TableIndex:
    """Group rows of a joined table by ``(noticeIdentifier, noticeVersion)``."""
    idx: TableIndex = {}
    for row in rows:
        idx.setdefault(notice_key(row), []).append(row)
    return idx


def _split_codes(raw: Optional[str]) -> list[str]:
    return [c.strip() for c in (raw or "").split(",") if c.strip()]


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# ── CPV (union across notice-level + all lot rows) ─────────────
def collect_cpv_codes(key: NoticeKey, classification_index: TableIndex) -> list[str]:
    codes: list[str] = []
    for row in classification_index.get(key, []):
        if (row.get("classificationType") or "").strip().lower() != "cpv":
            continue
        main = (row.get("mainClassificationCode") or "").strip()
        if main:
            codes.append(main)
        codes.extend(_split_codes(row.get("additionalClassificationCodes")))
    return _dedupe_preserve_order(codes)


def matches_cpv(key: NoticeKey, classification_index: TableIndex, cpv_prefixes: list[str]) -> bool:
    codes = collect_cpv_codes(key, classification_index)
    return any(c.startswith(prefix) for c in codes for prefix in cpv_prefixes)


# ── NUTS (place-of-performance, falling back to buyer org) ─────
def collect_place_nuts(key: NoticeKey, place_index: TableIndex) -> list[str]:
    codes = [
        (row.get("placePerformanceCountrySubdivision") or "").strip()
        for row in place_index.get(key, [])
    ]
    return _dedupe_preserve_order([c for c in codes if c])


def collect_buyer_nuts(key: NoticeKey, organisation_index: TableIndex) -> list[str]:
    codes = [
        (row.get("organisationCountrySubdivision") or "").strip()
        for row in organisation_index.get(key, [])
        if (row.get("organisationRole") or "").strip().lower() == "buyer"
    ]
    return _dedupe_preserve_order([c for c in codes if c])


def collect_nuts_codes(key: NoticeKey, place_index: TableIndex, organisation_index: TableIndex) -> list[str]:
    codes = collect_place_nuts(key, place_index)
    if codes:
        return codes
    return collect_buyer_nuts(key, organisation_index)


def matches_nuts(
    key: NoticeKey,
    place_index: TableIndex,
    organisation_index: TableIndex,
    nuts_prefixes: list[str],
) -> bool:
    codes = collect_nuts_codes(key, place_index, organisation_index)
    return any(c.startswith(prefix) for c in codes for prefix in nuts_prefixes)


# ── Deadline (submissionTerms.publicOpeningDate) ────────────────
def get_deadline(key: NoticeKey, submission_index: TableIndex) -> Optional[str]:
    for row in submission_index.get(key, []):
        value = (row.get("publicOpeningDate") or "").strip()
        if value:
            return value
    return None


def still_open(deadline_str: Optional[str], today: date) -> bool:
    """Unknown or unparsable deadline -> keep. Known past date -> drop."""
    if not deadline_str:
        return True
    try:
        parsed = date.fromisoformat(deadline_str[:10])
    except ValueError:
        return True
    return parsed >= today


# ── Title / description / value (purpose table) ─────────────────
def pick_purpose_row(key: NoticeKey, purpose_index: TableIndex) -> Optional[dict]:
    """Prefer the notice-level purpose row (empty lotIdentifier); else first lot row."""
    rows = purpose_index.get(key, [])
    for row in rows:
        if (row.get("lotIdentifier") or "").strip() == "":
            return row
    return rows[0] if rows else None


# ── Location (place city, else buyer city, else "") ─────────────
def location_for(key: NoticeKey, place_index: TableIndex, organisation_index: TableIndex) -> str:
    for row in place_index.get(key, []):
        city = (row.get("placePerformanceCity") or "").strip()
        if city:
            return city
    for row in organisation_index.get(key, []):
        if (row.get("organisationRole") or "").strip().lower() != "buyer":
            continue
        city = (row.get("organisationCity") or "").strip()
        if city:
            return city
    return ""


# ── Version parsing + dedup ──────────────────────────────────────
def parse_version(raw_version) -> int:
    """"01" and "1" both -> 1. Unparsable -> 0 (sorts as oldest)."""
    try:
        return int(str(raw_version).strip())
    except (TypeError, ValueError):
        return 0


def dedup_latest_version(rows: list[dict]) -> list[dict]:
    """One row per noticeIdentifier: highest numeric noticeVersion wins."""
    best: dict[Optional[str], tuple[int, dict]] = {}
    for row in rows:
        nid = row.get("noticeIdentifier")
        version = parse_version(row.get("noticeVersion"))
        current = best.get(nid)
        if current is None or version > current[0]:
            best[nid] = (version, row)
    return [row for _, row in best.values()]


def _publication_sort_key(row: dict) -> datetime:
    raw = (row.get("publicationDate") or "").strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def cap_by_publication_date(rows: list[dict], max_fetch: int) -> list[dict]:
    ordered = sorted(rows, key=_publication_sort_key, reverse=True)
    return ordered[:max_fetch]


# ── Output schema assembly ───────────────────────────────────────
def build_survivor(
    notice_row: dict,
    classification_index: TableIndex,
    place_index: TableIndex,
    purpose_index: TableIndex,
    organisation_index: TableIndex,
    submission_index: TableIndex,
) -> dict:
    key = notice_key(notice_row)
    purpose_row = pick_purpose_row(key, purpose_index) or {}
    estimated_value = (purpose_row.get("estimatedValue") or "").strip() or None

    return {
        "noticeIdentifier": notice_row.get("noticeIdentifier"),
        "noticeVersion": notice_row.get("noticeVersion"),
        "noticeType": notice_row.get("noticeType"),
        "publicationDate": notice_row.get("publicationDate"),
        "title": purpose_row.get("title") or "",
        "description": purpose_row.get("description") or "",
        "estimatedValue": estimated_value,
        "cpvCodes": collect_cpv_codes(key, classification_index),
        "nutsCodes": collect_nuts_codes(key, place_index, organisation_index),
        "location": location_for(key, place_index, organisation_index),
        "publicOpeningDate": get_deadline(key, submission_index),
    }


# ── PIPELINE (network-free, fully testable) ──────────────────────
def run_pipeline(
    tables: dict[str, list[dict]],
    *,
    cpv_prefixes: list[str] = CPV_PREFIXES,
    nuts_prefixes: list[str] = NUTS_PREFIXES,
    max_fetch: int = MAX_FETCH,
    today: Optional[date] = None,
    verbose: bool = True,
) -> tuple[list[dict], dict[str, int]]:
    """Join, filter, dedup, and cap. Returns (survivors, stage_counts)."""
    today = today or date.today()

    notices = tables.get("notice", [])
    classification_index = index_by_notice(tables.get("classification", []))
    place_index = index_by_notice(tables.get("placeOfPerformance", []))
    purpose_index = index_by_notice(tables.get("purpose", []))
    organisation_index = index_by_notice(tables.get("organisation", []))
    submission_index = index_by_notice(tables.get("submissionTerms", []))
    # If submissionTerms never joined at all (table absent from every day's
    # export), skip the deadline filter entirely rather than treat every
    # notice as unknown-but-still-filterable — there is nothing to filter on.
    has_submission_table = "submissionTerms" in tables

    counts: dict[str, int] = {"fetched": len(notices)}

    competition = [n for n in notices if n.get("noticeType") in COMPETITION_NOTICE_TYPES]
    counts["competition"] = len(competition)

    cpv_filtered = [n for n in competition if matches_cpv(notice_key(n), classification_index, cpv_prefixes)]
    counts["cpv45"] = len(cpv_filtered)

    region_filtered = [
        n for n in cpv_filtered if matches_nuts(notice_key(n), place_index, organisation_index, nuts_prefixes)
    ]
    counts["region"] = len(region_filtered)

    if has_submission_table:
        open_notices = [
            n for n in region_filtered if still_open(get_deadline(notice_key(n), submission_index), today)
        ]
    else:
        open_notices = list(region_filtered)
    counts["still_open"] = len(open_notices)

    deduped = dedup_latest_version(open_notices)
    counts["deduped"] = len(deduped)

    capped = cap_by_publication_date(deduped, max_fetch)
    counts["capped"] = len(capped)

    survivors = [
        build_survivor(n, classification_index, place_index, purpose_index, organisation_index, submission_index)
        for n in capped
    ]

    if verbose:
        print(f"Fetched:       {counts['fetched']}")
        print(f"Competition:   {counts['competition']}")
        print(f"CPV 45:        {counts['cpv45']}")
        print(f"Region match:  {counts['region']}")
        print(f"Still open:    {counts['still_open']}")
        print(f"Deduped:       {counts['deduped']}")
        print(f"Capped:        {counts['capped']}")

    return survivors, counts


# ── MAIN (network + filesystem side effects) ─────────────────────
def main() -> None:
    tables = fetch_all_days(FETCH_DAYS_BACK)
    survivors, _counts = run_pipeline(tables)

    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "raw_notices.json"
    out_path.write_text(json.dumps(survivors, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(survivors)} survivors to {out_path}")


if __name__ == "__main__":
    main()
