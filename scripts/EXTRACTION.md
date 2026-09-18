# Tender extraction prototype

Run commands from `hackathon/tender-backend` (Python 3.11+).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-extraction.txt pytest
python -m pytest tests
```

## Offline smoke test (no key)

```bash
python scripts/extract_tender.py tests/fixtures/extraction/explicit.txt \
  --replay tests/fixtures/extraction/explicit.replay.json \
  --audit /tmp/explicit-audit.json
```

Replace `explicit` with `unknown` or `restrictions` for the other cases.
Replay feeds authored JSON responses through the real validation/merge pipeline.
It does **not** run an LLM or establish model extraction accuracy.

## Live Gemini test

Set `GEMINI_API_KEY` and `GEMINI_MODEL` in the backend `.env` file (or environment).
Use a model ID with structured-output support that is available in your AI Studio
account. The prototype does not assume free-tier model availability.

```bash
python scripts/extract_tender.py tests/fixtures/extraction/unknown.txt \
  --audit /tmp/unknown-live-audit.json
python scripts/extract_tender.py /path/to/tender.pdf \
  --audit /tmp/tender-live-audit.json > /tmp/tender-fields.json
```

For a package, pass a directory containing PDF, UTF-8 TXT or Markdown documents
for **one tender/lot**. All nested files are considered. Unsupported formats fail
explicitly; extract GAEB/Office documents to text first. TXT form-feed characters
(`\f`) represent page breaks. A blank/image-only PDF page fails with an OCR-required
error; OCR and downloading are outside this prototype.

All pages are processed. Long pages are split into 12,000-character chunks with
500-character overlap; this is a rough token allowance, not an exact token count.
Short pages use one request each, so long packages can use substantial API quota.
No silent total-document truncation occurs. A failed chunk aborts the run.
Malformed/schema-invalid output gets exactly one retry per chunk. HTTP/network
errors fail immediately. The CLI exits nonzero on failure and writes no new result.

Stdout contains only the required extraction JSON. `--audit` stores every source
chunk and its extracted fields, processing counts, and conflicts. This is chunk-level
provenance, not a claim that each field has a verified supporting quote. Treat this
file as containing the original document's data. `complete` means all supplied pages
were processed, not that every extracted fact is correct.

Lists are deduplicated exactly. Different non-null scalar values are retained in
`conflicts`, with the final field set to null and `requires_review=true`. This also
applies to differently worded trades/references: the prototype deliberately avoids
an additional model call that might silently resolve contradictions. Check the audit
before using the final fields for a bid decision.

## Review three live outputs

Run all three `.txt` fixtures **without** `--replay`, saving separate audit files.
Compare with the authored `.replay.json` reference values; equivalent wording is OK.

| Fixture | Checks for reviewer |
| --- | --- |
| explicit | main_contractor; dates 2027-03-01–2027-06-30; value 500000; guarantee 25000; 40%; ISO 9001; three references/five years |
| unknown | Malerarbeiten; role/value/construction dates null; subcontracting permission must not set role; submission date must not set start |
| restrictions | subcontractor; TRGS 519; value and euro guarantee null; 5% guarantee and night-only restriction retained; hospital operation complexity |

Record reviewer, date, model ID and findings beside saved live outputs. No live
outputs or human signoff are supplied with this prototype. The referenced real sample
was not found in the inspected checkout; run it when available. An automated test
separately proves page 11 reaches extraction and its requirement survives merging.

## Integration boundary

`app.llm.extraction.extract_pages(pages, generate)` returns `(fields, audit)`.
`extract_chunk(text, generate)` is available for already bounded source text.
The extraction model accepts only main_contractor/subcontractor/null for role.
It is independent of the frozen `Tender`/frontend models, which still require an
adapter/contract update before Story 1.2 integration: `estimated_value_eur` maps to
`value_eur`, `complexity_markers` needs a home, and null trade/role/references must
remain unknown rather than being coerced to an invented role or requirement.

Gemini REST configuration follows Google's structured-output API:
https://ai.google.dev/gemini-api/docs/generate-content/structured-output

If generation returns HTTP 404, check model availability for your API key:

```bash
python scripts/extract_tender.py --list-models
```

Choose a text model with structured-output support from the returned IDs, and pass
it with `--model`. Listing confirms generateContent support, not free-tier quota or
structured-output support. HTTP failures now include Gemini's error explanation
(with the configured API key redacted).

## Real ZIP test: 2.653.880, Gemini 3.8 Flash

The ZIP input now uses two stages:

1. Inventory **every PDF filename** in the ZIP, including nested directories. Send
   the full title inventory to Gemini 3.8 Flash. Validate exactly one include/exclude
   decision per PDF, with reasons and the relevant extraction fields.
2. Open only included PDFs, extract all their pages, and send their text to Gemini.
   Adjacent pages from the same PDF are packed into roughly 12,000-character requests
   to retain context and reduce calls. Long chunks overlap. PDFs are never unpacked
   onto disk. Non-PDF ZIP members are listed in the report but not processed.

Here, “title” means the filename without `.pdf`, not the PDF metadata Title or an
OCR-derived cover heading. Selection is deliberately auditable: a relevant document
can have an uninformative filename, so title filtering cannot guarantee package-wide
coverage. `complete` refers to all pages of the **selected** PDFs.

Preview selection without opening any PDF content:

```bash
/tmp/tender-extraction-venv/bin/python scripts/extract_tender.py \
  app/llm/2.653.880_Ausschreibungsunterlagen.zip \
  --model gemini-3.8-flash --selection-only \
  --selection-report /tmp/tender-2653880-selection.json
```

Run the full extraction (one tender per ZIP):

```bash
/tmp/tender-extraction-venv/bin/python scripts/extract_tender.py \
  app/llm/2.653.880_Ausschreibungsunterlagen.zip \
  --model gemini-3.8-flash \
  --selection-report /tmp/tender-2653880-selection.json \
  --audit /tmp/tender-2653880-audit.json \
  > /tmp/tender-2653880-fields.json
```

Both commands perform fresh title selection, so choices can vary between runs.
The selection report is written before opening PDFs and remains available if
extraction fails. The audit embeds the exact selection used for its run.

An opt-in integration test runs the same CLI with Gemini 3.8 Flash and verifies the
schema, complete inventory, inclusion of the LV, all selected documents reaching
extraction, and zero excluded documents in extraction output:

```bash
RUN_GEMINI_ZIP_TEST=1 /tmp/tender-extraction-venv/bin/python -m pytest \
  tests/test_tender_zip_live.py -v -s
```

Ordinary `pytest tests` skips this network/API-quota test. It does not replace human
source review. For this package, check that the EUR 250,000 conditional security
threshold in form 214 is **not** reported as the estimated contract value, percentage
security is not converted to a euro guarantee, and blank dates/unchecked form options
are not treated as established requirements. PDF text extraction can lose checkbox
state and drawn/interactive form values; inspect the actual PDF for those details.

### Observed live run (2026-09-18)

The CLI completed against the supplied ZIP using `gemini-3.8-flash`:
24 PDF titles evaluated, 17 PDFs selected, 127 pages processed in 32 extraction
chunks (plus the title-selection call). Saved artifacts for this workspace:

- `/tmp/tender-2653880-selection.json`
- `/tmp/tender-2653880-fields.json`
- `/tmp/tender-2653880-audit.json`

Validated the schema and verified that the set of PDFs in extraction chunks exactly
matches the selected set. Source spot-check: LV page 8 gives 18.12.2026, and the
extracted construction end is `2026-12-18`. Estimated value and euro guarantee remain
null; the conditional EUR 250,000 threshold from form 214 was not mistaken for value.

The output requires review. `trade_type` and `references_required` are null because
the conservative merger found different strings across chunks. The audit preserves
all alternatives: heating/BHKW/electrical descriptions, three comparable references
from five years (form 124), comparable installations from five years (LV page 12),
and a selectivity-study reference from three years. These may be complementary,
not contradictory; semantic consolidation is a remaining limitation. Certification
and complexity lists can likewise contain semantically duplicated wording. This
run verifies the title-first pipeline and selected facts, not every extracted claim
or a human signoff on the complete tender.

### Frontend integration update

The current merger preserves differing trade descriptions and reference requirements
in the final string fields instead of nulling them. Original alternatives appear in
`aggregated_fields`; scalar conflicts remain unresolved with `field_status="conflict"`.
The historical run above records the earlier merger. Re-merging its saved Gemini
chunks with the new code produces `/tmp/tender-2653880-frontend-result.json` without
additional model calls. See [FRONTEND-INTEGRATION.md](FRONTEND-INTEGRATION.md) for the
upload/poll API and the typed Angular service.
