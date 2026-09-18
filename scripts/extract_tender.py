"""Run from the backend directory: python scripts/extract_tender.py --help."""
import argparse
import json
import logging
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.llm.extraction import ExtractionError, GeminiClient, extract_pages, list_gemini_models


def read_pages(path, skipped_pages=None):
    skipped_pages = [] if skipped_pages is None else skipped_pages
    files = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    pages = []
    for file in files:
        if file.suffix.lower() == ".pdf":
            import pdfplumber
            with pdfplumber.open(file) as pdf:
                from app.llm.pdf_reader import read_pdf_pages
                pages.extend(read_pdf_pages(pdf, str(file), skipped_pages))
        elif file.suffix.lower() in {".txt", ".md"}:
            pages.extend((str(file), i, text) for i, text in
                         enumerate(file.read_text(encoding="utf-8").split("\f"), 1))
        else:
            raise ExtractionError(f"Unsupported file {file}; supply PDF/text files or a directory containing only those")
    return pages


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Extract all pages of one tender package. JSON to stdout, evidence to audit file.")
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--list-models", action="store_true", help="List available generateContent model IDs for your API key")
    parser.add_argument("--model", default=os.getenv("GEMINI_MODEL"))
    parser.add_argument("--audit", type=Path, default=Path("extraction-audit.json"))
    parser.add_argument("--selection-only", action="store_true", help="For ZIPs: classify every PDF title and save the selection without opening PDFs")
    parser.add_argument("--selection-report", type=Path, default=Path("extraction-selection.json"))
    parser.add_argument("--chunk-chars", type=int, default=12000)
    parser.add_argument("--replay", type=Path, help="Offline plumbing test: JSON array of canned model responses (not an LLM)")
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        if args.list_models:
            print("\n".join(list_gemini_models(os.getenv("GEMINI_API_KEY", ""))))
            return 0
        if args.source is None:
            parser.error("source is required unless --list-models is used")
        if args.replay:
            responses = iter(json.loads(args.replay.read_text()))
            def generate(prompt, schema):
                try:
                    value = next(responses)
                except StopIteration as exc:
                    raise ExtractionError("Replay responses exhausted") from exc
                return value if isinstance(value, str) else json.dumps(value)
        else:
            generate = GeminiClient(os.getenv("GEMINI_API_KEY", ""), args.model or os.getenv("GEMINI_MODEL", ""))
        selection = None
        skipped_pages = []
        if args.source.suffix.lower() == ".zip":
            from app.llm.tender_zip import inventory_zip, select_titles, read_selected_pages
            selection = select_titles(inventory_zip(args.source), generate)
            selection["model"] = args.model or os.getenv("GEMINI_MODEL", "")
            args.selection_report.write_text(json.dumps(selection, ensure_ascii=False, indent=2), encoding="utf-8")
            count = sum(item["decision"] == "include" for item in selection["pdfs"])
            print(f"Selected {count}/{len(selection['pdfs'])} PDFs; report: {args.selection_report}", file=sys.stderr)
            if args.selection_only:
                print(json.dumps(selection, ensure_ascii=False, indent=2))
                return 0
            pages = read_selected_pages(args.source, selection)
            skipped_pages = selection["skipped_pages"]
        else:
            if args.selection_only:
                parser.error("--selection-only requires a ZIP source")
            pages = read_pages(args.source, skipped_pages)
        result, audit = extract_pages(pages, generate, args.chunk_chars, pack_pages=selection is not None)
        if selection is not None:
            audit["selection"] = selection
            audit["coverage"] = "All pages of title-selected PDFs; excluded PDFs and non-PDF files were not read"
        audit["skipped_pages"] = skipped_pages
        audit["model"] = args.model or os.getenv("GEMINI_MODEL", "")
        audit["mode"] = "replay" if args.replay else "gemini"
        args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(result.model_dump_json(indent=2))
        print(f"Audit: {args.audit}; review required: {audit['requires_review']}", file=sys.stderr)
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
