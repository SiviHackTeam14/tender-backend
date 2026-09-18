"""Run reasoning on an explicitly supplied JSON array of hard-filter survivors."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from pydantic import TypeAdapter

from app.llm.reasoning import analyze, build_reasoning_prompt
from app.models import CompanyProfile, Tender


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--profiles", type=Path, default=ROOT / "app/data/profiles.json")
    parser.add_argument("--tenders", type=Path, required=True, help="JSON array already passed through hard filtering")
    parser.add_argument("--model", help="Defaults to GEMINI_MODEL or gemini-3.8-flash")
    parser.add_argument("--distances", type=Path, help="Optional JSON object mapping tender IDs to company-relative km")
    parser.add_argument("--output", type=Path, help="Write validated JSON here instead of stdout")
    parser.add_argument("--dry-run", action="store_true", help="Print the prompt without calling Gemini")
    args = parser.parse_args(argv)
    try:
        load_dotenv(ROOT / ".env")
        profiles = TypeAdapter(list[CompanyProfile]).validate_json(args.profiles.read_text(encoding="utf-8"))
        matches = [p for p in profiles if p.id == args.profile_id]
        if len(matches) != 1:
            raise ValueError("profile-id must identify exactly one profile")
        tenders = TypeAdapter(list[Tender]).validate_json(args.tenders.read_text(encoding="utf-8"))
        distances = json.loads(args.distances.read_text(encoding="utf-8")) if args.distances else None
        if args.dry_run:
            output = build_reasoning_prompt(matches[0], tenders, distances_km=distances)
        else:
            results = analyze(matches[0], tenders, distances_km=distances, model=args.model)
            output = json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
            print(f"Saved {args.output}", file=sys.stderr)
        else:
            print(output)
    except Exception as exc:
        print(f"Reasoning failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
