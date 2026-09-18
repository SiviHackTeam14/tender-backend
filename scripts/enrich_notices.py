"""LV document download + enrichment (Story 1.2).

Reads ``data/raw_notices.json`` (Story 1.1's output), groups survivors by their
publication day, re-fetches that day's OCDS export to find each notice's
document URL(s), hops through the notice's e-procurement platform to download
the actual Vergabeunterlagen (or skips + logs if the platform is locked or
unsupported), parses the package (GAEB first, then pdfplumber, then Gemini
Vision as a last resort), and runs Story 2.1's extraction prompt on the result.

Writes ``data/enriched_notices.json`` (every Story 1.1 survivor, enriched or
marked skipped/failed with a reason) and ``data/enrichment-log.jsonl`` (one
line per attempted stage, for auditing/debugging).

Everything above the ``if __name__ == "__main__":`` guard is import-safe: no
network calls or Gemini calls happen at module load time. Only ``main()`` (and
the functions it calls) touch the network, so tests can load this module with
``importlib`` and exercise the pure per-notice logic directly, same contract
as Story 1.1's ``scripts/prototype.py``.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# scripts/ is deliberately not a package (Story 1.1 convention); add the
# backend root to sys.path so `python scripts/enrich_notices.py` and
# importlib-from-path test loads both resolve `app.*` imports the same way
# scripts/extract_tender.py already does for its own app.llm imports.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.fetch.document_urls import (  # noqa: E402
    extract_document_urls,
    fetch_ocds_day,
    index_ocds_zip,
    parse_version,
)
from app.fetch.platform_adapters import (  # noqa: E402
    LockedError,
    UnreachableError,
    UnsupportedPlatformError,
    classify_platform,
    resolve_package,
)
from app.llm.extraction import (  # noqa: E402
    ExtractedRequirements,
    ExtractionError,
    GeminiClient,
)
from app.llm.extraction import extract_pages  # noqa: E402
from app.llm.lv_package import load_pages  # noqa: E402

MAX_LV_PAGES = 10  # epic-1-context §5.1 cost cap, enforced here (not in extract_pages)

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
RAW_NOTICES_PATH = DATA_DIR / "raw_notices.json"
ENRICHED_PATH = DATA_DIR / "enriched_notices.json"
LOG_PATH = DATA_DIR / "enrichment-log.jsonl"
PACKAGES_DIR = DATA_DIR / "lv_packages"

EXTRACTION_FIELDS = tuple(ExtractedRequirements.model_fields)
_LIST_FIELDS = {"certifications_required", "complexity_markers", "hidden_blockers"}


def _empty_extraction_dict() -> dict:
    return {name: ([] if name in _LIST_FIELDS else None) for name in EXTRACTION_FIELDS}


def stub_generate(prompt: str, schema: dict) -> str:
    """Deterministic offline stand-in for Gemini text extraction: a valid,
    all-null/empty ``ExtractedRequirements`` JSON. Used whenever
    ``GEMINI_API_KEY`` is not configured, so the pipeline still runs
    start-to-finish and writes valid output."""
    return json.dumps(_empty_extraction_dict())


def build_generators(api_key: str, model: str):
    """Return ``(generate, vision_generate, is_stub)``.

    Constructs real Gemini clients if ``api_key`` is set (mirrors
    ``app.api.extractions.get_generator``'s "real client or explicit failure"
    shape), else falls back to the null-value stub for text extraction and
    ``None`` for Vision (meaning: drop OCR-required pages rather than call
    anything)."""
    if not api_key:
        return stub_generate, None, True
    from app.llm.vision_ocr import GeminiVisionClient

    text_client = GeminiClient(api_key, model)
    vision_client = GeminiVisionClient(api_key, model)
    return text_client, vision_client, False


def group_by_day(notices: list[dict]) -> dict[str, list[dict]]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for notice in notices:
        day = (notice.get("publicationDate") or "")[:10]
        by_day[day].append(notice)
    return dict(by_day)


def log_event(log_file, notice: dict, stage: str, status: str, reason: Optional[str] = None, host: Optional[str] = None) -> None:
    entry = {
        "noticeIdentifier": notice.get("noticeIdentifier"),
        "noticeVersion": notice.get("noticeVersion"),
        "stage": stage,
        "status": status,
        "reason": reason,
        "host": host,
    }
    log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _skipped_record(notice: dict, reason: str) -> dict:
    record = dict(notice)
    record.update(_empty_extraction_dict())
    record.update(
        document_url=None,
        local_zip_path=None,
        extraction_method=None,
        extraction_status="skipped",
        extraction_skip_reason=reason,
    )
    return record


def _download_package(notice: dict, doc_urls: list[dict], packages_dir: Path, log_file) -> tuple[Optional[bytes], Optional[str], Optional[str]]:
    """Try each candidate document URL until one resolves to package bytes.

    Returns ``(zip_bytes, used_url, skip_reason)`` — exactly one of the first
    two, or ``skip_reason`` set, is non-``None``. Caches the first successful
    download to ``packages_dir/{noticeIdentifier}.zip``.
    """
    cache_path = packages_dir / f"{notice['noticeIdentifier']}.zip"
    if cache_path.exists():
        return cache_path.read_bytes(), "cached: " + cache_path.name, None

    last_reason = "no_document_url"
    for doc in doc_urls:
        url = doc.get("url")
        if not url:
            continue
        host = urlparse(url).netloc
        try:
            zip_bytes = resolve_package(url)
        except LockedError:
            last_reason = "login_required"
            log_event(log_file, notice, "platform_fetch", "skipped", last_reason, host)
            continue
        except UnsupportedPlatformError as exc:
            last_reason = "unsupported_platform"
            log_event(log_file, notice, "platform_fetch", "skipped", last_reason, exc.host)
            continue
        except UnreachableError:
            last_reason = "platform_unreachable"
            log_event(log_file, notice, "platform_fetch", "skipped", last_reason, host)
            continue
        packages_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(zip_bytes)
        return zip_bytes, url, None

    return None, None, last_reason


def enrich_one(notice: dict, doc_urls: list[dict], generate, vision_generate, packages_dir: Path, log_file) -> dict:
    """Enrich one Story 1.1 survivor. Never raises — every failure mode ends
    in a returned record with ``extraction_status`` set and a reason logged.
    """
    if not doc_urls:
        log_event(log_file, notice, "document_url", "skipped", "no_document_url")
        return _skipped_record(notice, "no_document_url")

    zip_bytes, used_url, skip_reason = _download_package(notice, doc_urls, packages_dir, log_file)
    if zip_bytes is None:
        return _skipped_record(notice, skip_reason or "platform_unreachable")

    record = dict(notice)
    record.update(_empty_extraction_dict())
    cache_path = packages_dir / f"{notice['noticeIdentifier']}.zip"
    record["document_url"] = used_url
    record["local_zip_path"] = str(cache_path.relative_to(packages_dir.parent))

    try:
        pages, method, meta = load_pages(zip_bytes, generate, vision_generate)
    except ExtractionError as exc:
        record["extraction_status"] = "failed"
        record["extraction_skip_reason"] = f"parse_failed: {exc}"
        log_event(log_file, notice, "parse", "failed", str(exc))
        return record

    record["extraction_method"] = method
    capped_pages = pages[:MAX_LV_PAGES]

    try:
        fields, _audit = extract_pages(capped_pages, generate)
    except ExtractionError as exc:
        record["extraction_status"] = "failed"
        record["extraction_skip_reason"] = f"extraction_failed: {exc}"
        log_event(log_file, notice, "extraction", "failed", str(exc))
        return record

    record.update(fields.model_dump())
    record["extraction_status"] = "ok"
    log_event(log_file, notice, "extraction", "ok")
    return record


def run_pipeline(notices: list[dict], generate, vision_generate, packages_dir: Path, log_file, fetch_day=fetch_ocds_day) -> tuple[list[dict], Counter]:
    """Network-touching orchestration, kept separate from ``main`` so tests can
    inject a mocked ``fetch_day`` and per-notice adapters without touching the
    filesystem-writing parts of ``main``."""
    by_day = group_by_day(notices)
    enriched: list[dict] = []
    counts: Counter = Counter()

    for day in sorted(by_day):
        day_notices = by_day[day]
        print(f"Day {day}: {len(day_notices)} notices")
        zip_bytes = fetch_day(day)
        if not zip_bytes:
            for notice in day_notices:
                log_event(log_file, notice, "document_url", "skipped", "ocds_fetch_failed")
                enriched.append(_skipped_record(notice, "ocds_fetch_failed"))
                counts["ocds_fetch_failed"] += 1
            continue

        index = index_ocds_zip(zip_bytes)
        for notice in day_notices:
            filename = index.get(notice["noticeIdentifier"], {}).get(
                parse_version(notice["noticeVersion"])
            )
            doc_urls = extract_document_urls(zip_bytes, filename) if filename else []
            record = enrich_one(notice, doc_urls, generate, vision_generate, packages_dir, log_file)
            enriched.append(record)
            counts[record["extraction_status"]] += 1

    return enriched, counts


def main() -> None:
    if not RAW_NOTICES_PATH.exists():
        raise SystemExit(
            f"{RAW_NOTICES_PATH} not found — run scripts/prototype.py (Story 1.1) first"
        )
    notices = json.loads(RAW_NOTICES_PATH.read_text(encoding="utf-8"))

    import os

    api_key = os.getenv("GEMINI_API_KEY", "")
    model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    generate, vision_generate, is_stub = build_generators(api_key, model)
    if is_stub:
        print("GEMINI_API_KEY not set — extraction fields will be null (stub mode)")

    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("w", encoding="utf-8") as log_file:
        # Pass fetch_ocds_day by the bare global name (resolved at call time,
        # not via run_pipeline's default parameter, which is bound once at
        # def-time) so tests can monkeypatch this module's fetch_ocds_day.
        enriched, counts = run_pipeline(notices, generate, vision_generate, PACKAGES_DIR, log_file, fetch_day=fetch_ocds_day)

    ENRICHED_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nWrote {len(enriched)} enriched notices to {ENRICHED_PATH}")
    for status, count in sorted(counts.items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
