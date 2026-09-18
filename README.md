# TenderPilot — Backend

**Hackathon:** SiviHack 2026 · Track 2 · Sponsor: Arctis AI
**Team:** Three Out of Forty

## What is this product?

A construction company can only bid on ~3 of the ~40 public tenders published every
week. Someone has to read every "Ausschreibung" (tenders) by
hand before they even know if a tender is worth chasing.

**TenderPilot** automates the reading step first, and is designed to grow into a
full triage assistant:

1. **Upload a tender ZIP** → the backend picks the relevant PDFs with Gemini, reads
   them, and extracts 12 structured requirement fields (trade type, required role,
   construction window, references required, guarantee amount, estimated value,
   certifications, complexity markers, hidden blockers, ...).
2. *(Designed, not wired up yet)* A **hard filter** (no LLM — geography, deadline,
   budget, role) narrows ~40 tenders down to the ones worth reasoning about.
3. *(Designed, not wired up yet)* A **Gemini bid/no-bid reasoning** step scores the
   survivors against a company profile on 5 criteria (reference eligibility,
   financial capacity, regulatory familiarity, competitive position, strategic
   fit) and explains, in plain language, which 3 tenders deserve the estimating
   team's time this week — and why the rest don't.

This backend is the **FastAPI service** that currently exposes step 1
(document extraction) as a REST API for the [Angular frontend](../frontend). The
hard-filter and reasoning modules already exist in the codebase (`app/filters`,
`app/llm/reasoning.py`) but are not yet called from the API — see
[Current limitations](#current-limitations).

## Setup and running the demo

Requires **Python 3.11+**, **Node.js 22.22.3+ or 24.15+**, npm, and a Gemini API key.
Keep the repositories in sibling directories named `tender-backend` and
`tender-frontend`. The commands below use Bash.

### One-time setup

From the directory containing both repositories:

```bash
cd tender-backend
python3 --version  # Must be 3.11 or newer.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

cd ../tender-frontend
npm ci
```

Create `tender-backend/.env` with your actual key; never commit this file:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
```

The backend and extraction CLI load this file automatically; terminal environment
injection is not required. Existing environment variables take precedence over
values in `.env`.

### Start the backend and frontend together

From the directory containing both repositories, run this block in one terminal:

```bash
bash <<'SH'
set -e

(
  cd tender-backend
  exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
backend_pid=$!

trap 'kill "$backend_pid" 2>/dev/null || true; wait "$backend_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT TERM

cd tender-frontend
npm start
SH
```

Open **http://localhost:4200**. Press **Ctrl+C** to stop both services.
Use one Uvicorn worker; this command avoids automatic reloads, which would discard
in-memory extraction jobs.

To test the full flow:

1. Upload a tender ZIP, such as the locally available
   `tender-backend/app/llm/2.653.880_Ausschreibungsunterlagen.zip`.
2. Click **Extract JSON** and follow the progress; a large package can take several minutes.
3. Check the JSON preview and click **Download JSON**.
4. Open the **source audit** to inspect the extracted evidence.

This tests **frontend → backend → Gemini → JSON**. Live extraction uses Gemini
quota. The result contains the 12 extraction fields; missing scalar values remain
`null`. No company profile, suitability verdict or ranking is involved. Existing
reasoning logic is reserved for the later filtering-and-reasoning stage.

- Health check: `curl http://localhost:8000/health` → `{"status":"ok"}`
- Interactive API explorer: <http://localhost:8000/docs>

### Start only the backend

From `tender-backend`:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use this instead of the combined command when testing the API alone.

### Try the extraction API directly

With the backend running, use another terminal in `tender-backend`:

```bash
curl --fail-with-body -sS \
  -F 'file=@app/llm/2.653.880_Ausschreibungsunterlagen.zip' \
  http://localhost:8000/api/extractions
```

Use your own ZIP path if the sample is unavailable. The response contains
`id`, `status_url`, `audit_url` and `data_url`.

Copy the returned ID into `JOB_ID`, then poll:

```bash
JOB_ID='paste-the-returned-id-here'

curl --fail-with-body -sS \
  "http://localhost:8000/api/extractions/$JOB_ID" \
  | .venv/bin/python -m json.tool
```

Repeat until `status` is `completed`. If it is `failed`, inspect `error.message`.
Once completed, download the data and audit:

```bash
curl --fail -sS \
  "http://localhost:8000/api/extractions/$JOB_ID/data" \
  -o /tmp/tender-data.json

curl --fail -sS \
  "http://localhost:8000/api/extractions/$JOB_ID/audit" \
  -o /tmp/tender-audit.json

.venv/bin/python -m json.tool /tmp/tender-data.json
```

The data endpoint returns only the extracted fields; the audit is separate.
Both endpoints return HTTP 409 before successful completion, or HTTP 404 if the
job is unknown or expired. Results expire after one hour and are lost on restart.

### Run extraction as a standalone script

From `tender-backend`, without starting either server:

```bash
.venv/bin/python scripts/extract_tender.py \
  app/llm/2.653.880_Ausschreibungsunterlagen.zip \
  --model gemini-3.8-flash \
  --audit /tmp/tender-audit.json \
  --selection-report /tmp/tender-selection.json \
  > /tmp/tender-data.json
```

Replace the source path with your own ZIP if needed. JSON is written to the output
file; progress and errors appear in the terminal. See
[`scripts/EXTRACTION.md`](scripts/EXTRACTION.md) for offline replay fixtures,
page coverage and audit details.

### Run tests

Backend tests, from `tender-backend`:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

The default suite uses fake Gemini responses and makes no live Gemini calls.
Live tests are opt-in and skipped unless their enable flags are set. Coverage
includes uploads, PDF parsing, title selection, retries, JSON downloads, extraction
isolation from reasoning, capacity limits, CORS and the OpenAPI contract.

Frontend tests and production build, from `tender-frontend`:

```bash
npm test
```

These tests make no live Gemini calls. The production build may need internet
access to inline the configured Google Fonts. To run only the extraction-flow
and adapter tests:

```bash
npm run test:extraction
```
## Tech stack

| Layer | Choice |
|---|---|
| API framework | [FastAPI](https://fastapi.tiangolo.com/) + Uvicorn |
| Validation | Pydantic v2 |
| LLM | Google Gemini (`gemini-3.8-flash` by default) via `generateContent` REST API |
| PDF parsing | `pdfplumber` (text, AcroForm fields, checkbox/radio states) |
| Language | Python 3.11+ |
| Testing | pytest, httpx (fake Gemini transport for offline tests) |

## Dataset / API / library used

- **Public tender data:** [oeffentlichevergabe.de](https://oeffentlichevergabe.de)
  notice-export API (CC0 licence, no API key required) — the source for German
  public construction tenders (CPV prefix `45`, filtered by NUTS region).
- **Real-world sample tender:** the `33_61_2026_Ausschreibungsunterlagen` folder
  in this repo (Rolandbrunnen Nordhausen, incl. a GAEB `.x83` bill-of-quantities
  file) used for extraction testing/fixtures.
- **LLM:** Google Gemini API (`gemini-3.8-flash`) — PDF title selection and
  structured requirement extraction from the LV documents.
- **Python libraries** (`requirements.txt`):
  ```
  fastapi
  uvicorn[standard]
  pydantic>=2,<3
  python-dotenv
  requests
  pytest
  pdfplumber>=0.11,<1
  python-multipart>=0.0.20,<1
  ```
  Dev/test extras (`requirements-dev.txt`): `pytest`, `httpx`.
  Extraction extras (`requirements-extraction.txt`): `Pillow` (image handling
  for scanned/image-only pages).

## Current limitations

- **Single-process, in-memory jobs.** Extraction jobs and results live in
  memory for one hour and are lost on restart. Run exactly **one** Uvicorn
  worker — this is a local, single-user demo setup, not a production
  deployment (no auth, no persistent/shared job storage).
- **Upload limits.** 50 MiB max ZIP size, 200 PDFs max, 250 MiB max
  uncompressed PDF data per archive.
- **Image-only pages need OCR.** Genuinely blank pages are skipped
  automatically; non-blank scanned/image-only pages that can't be read fail
  extraction with an explicit error rather than silently guessing.
  
