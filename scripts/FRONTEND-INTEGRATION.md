# Connect the frontend to tender extraction

The backend accepts one tender ZIP, selects relevant PDF filenames with Gemini,
extracts only those PDFs, and returns a typed result. The API defaults to
`gemini-3.8-flash`; `GEMINI_MODEL` can override it on the server. The browser never
receives or submits the Gemini API key.

## Start the backend

From `hackathon/tender-backend`:

```bash
/tmp/tender-extraction-venv/bin/pip install -r requirements.txt
/tmp/tender-extraction-venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For a fresh environment, create a Python 3.11+ virtualenv and install
`requirements.txt` there. Set the backend `.env`:

```dotenv
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-3.8-flash
```

API explorer: <http://localhost:8000/docs>. Schema: `/openapi.json`.
CORS permits the existing Angular dev origin `http://localhost:4200`.

## HTTP contract

| Request | Response |
| --- | --- |
| `POST /api/extractions` with multipart field `file` | `202 {id, status_url, audit_url}` and a Location header |
| `GET /api/extractions/{id}` | Job status, progress, result or error |
| `GET /api/extractions/{id}/audit` | Full source-chunk audit after completion; 409 otherwise |

```bash
curl -sS -F 'file=@app/llm/2.653.880_Ausschreibungsunterlagen.zip' \
  http://localhost:8000/api/extractions
```

Copy the returned `id` and poll:

```bash
curl -sS http://localhost:8000/api/extractions/REPLACE_WITH_JOB_ID | python3 -m json.tool
```

States: `queued` → `selecting` → `reading` → `extracting` → `completed` or `failed`.
During extraction, `progress.completed_chunks / progress.total_chunks` is real
chunk progress. During title selection and PDF reading, show an indeterminate
indicator. Do not manufacture percentages for those stages. A completed job can
still have `result.requires_review=true`.

Every status response has `id`, `filename`, `model`, `status`, `progress`, `result`,
and `error`. `result` is null until successful completion; `error` is null unless
failed. An extraction failure remains a GET 200 job with `status="failed"` and
`error: {code, message}`. HTTP failures during upload/polling use
`detail: {code, message}`. Missing multipart data uses FastAPI's standard 422
validation-error array.

Other HTTP codes: 413 oversized upload/archive, 415 non-ZIP filename, 422 invalid
ZIP/no PDFs, 429 occupied workers/result store (Retry-After: 10), 503 missing server
configuration, 404 unknown/expired job. Do not automatically re-upload after an
uncertain network failure: it could duplicate a running job and Gemini calls.

## Result fields and display

`result.fields` contains the 12 extraction fields. Additionally:

- `field_status[field]`: `extracted`, `not_found`, `conflict`, or `needs_review`.
- `aggregated_fields`: individual trade/reference descriptions that were combined.
- `review_reasons`: why a combined field needs a compatibility/scope check.
- `skipped_pages`: confirmed blank pages with their original filename and page number.
- `evidence[field]`: findings with `file`, `pages`, and the extracted `value`.
- `conflicts`: unresolved scalar alternatives (dates, role, amounts, percentages).
- `documents`: every reviewed PDF title, include/exclude decision, relevant fields,
  and selection reason. `ignored_non_pdf` lists other archive members.
- `pages_processed`, `chunks_processed`, `requires_review`, and
  `coverage="selected_pdfs_only"`.

Render `not_found` as “Not stated in selected documents”, and `conflict` as
“Conflicting requirements — review sources”. Render `needs_review` as “Combined requirements — review sources”. None of these statuses means zero or no requirement.
Format known EUR values/dates in the UI. Render descriptions as text, never HTML.
`evidence` points to the page(s) of an extraction chunk; it is not a verified
word-for-word citation. `/audit` contains the corresponding original extracted text.

Trades are combined with semicolons and reference requirements with newlines.
This preserves complementary findings without another LLM call. The merger does
not prove logical compatibility of free-text claims; any aggregation is marked `needs_review` and sets `requires_review=true`.
Show its individual sources when expanded. Arrays deduplicate exact wording, not semantic synonyms. Numeric,
role and date conflicts still produce null plus explicit conflict status.

This is a separate extraction contract, **not** a complete `Tender`: IDs, notice
URLs, distances, location and submission deadlines still come from the notice
pipeline. In that integration, `estimated_value_eur` maps to `Tender.value_eur`.
The Python and TypeScript `Tender` models now support extraction nulls and
`complexity_markers`. Roles are `main_contractor`, `subcontractor`, or null; migrate
legacy `either` values to null. Do not cast raw extraction fields to `Tender` or
invent missing notice values.

Use `extractForTender(file, notice)` to upload and enrich an existing notice. It
emits `TenderExtractionJob`: the usual job plus `tender`, populated on completion.
The adapter maps `estimated_value_eur` to `value_eur`, preserves notice metadata,
and keeps known notice values when a document field is `not_found`. Conflicts
retain extraction nulls, clearing the previous value. Combined text marked
`needs_review` is included, with its review details retained in `job.result`.
Keep that result alongside the enriched tender; the tender alone does not carry
provenance or review status. A preserved notice value is not document-confirmed.

```typescript
this.extractor.extractForTender(file, notice).subscribe(job => {
  if (job.status === 'completed' && job.tender && job.result) {
    // Display job.tender; show job.result.requires_review and field_status.
    // Expand job.result.evidence and review_reasons for source inspection.
  }
});
```

## Angular service already provided

- `src/app/models/extraction.ts`: typed request/result contract.
- `src/app/services/extraction.service.ts`: upload, get, watch, extract, extractForTender and audit URL.
- `src/app/services/tender-extraction.adapter.ts`: pure mapping to the shared Tender model.
- `provideHttpClient()` is registered in `app.config.ts`.

The service uses the existing `environment.apiUrl`. It intentionally always calls
the backend; the existing unrelated `useMock` flag does not fake extraction.

Example inside a component (add normal Angular imports):

```typescript
private readonly extractor = inject(ExtractionService);
private readonly destroyRef = inject(DestroyRef);
readonly extractionJob = signal<ExtractionJob | null>(null);
readonly extractionError = signal<string | null>(null);

onTenderSelected(file: File): void {
  this.extractionJob.set(null);
  this.extractionError.set(null);
  this.extractor.extract(file)
    .pipe(takeUntilDestroyed(this.destroyRef))
    .subscribe({
      next: job => {
        this.extractionJob.set(job);
        if (job.status === 'failed') {
          this.extractionError.set(job.error?.message ?? 'Extraction failed');
        }
      },
      error: () => this.extractionError.set('Could not contact extraction API'),
    });
}
```

Prevent a second upload while one is running. `watch(id)` polls every 1.5 seconds,
avoids overlapping polls, emits the terminal state and completes. Unsubscribing
stops browser polling but does not cancel the server job. For reload recovery,
use `upload(file)`, store its returned ID, and resume with `watch(id)`.

## Verification and deployment scope

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

API tests exercise multipart upload, actual PDF parsing, title selection/exclusion,
progress, success/failure, one retry, capacity limits, CORS and OpenAPI using a fake
Gemini transport. The opt-in live Gemini test remains documented in EXTRACTION.md.

Jobs/results live in memory for one hour and are lost on server restart. Run
**one Uvicorn process**, without `--workers` > 1. The demo allows two running jobs,
retains at most 20 jobs, and deletes temporary uploads when processing ends.
Limits: 50 MiB ZIP, 200 PDFs, 250 MiB total uncompressed PDF data. This is a local
single-user integration; authentication and durable/shared job storage are not
implemented. Public or multi-worker deployment needs those additions.

## PDF reading and page coverage

Page text is supplemented with AcroForm values and per-widget checkbox/radio states.
Inherited fields and PDF string encodings are supported; nearby printed labels help
interpret field names. Only demonstrably blank pages are skipped and recorded in
`skipped_pages`. Image-only or otherwise unreadable nonblank pages still fail with
an OCR-required error. `pages_processed` counts pages sent for extraction, excluding
those confirmed blanks. Chunk overlap crosses page boundaries within each PDF and
source findings retain the actual contributing page numbers.
