# TenderPilot — Backend

**Hackathon:** SiviHack 2026 · Track 2 · Sponsor: Arctis AI
**Team:** Three Out of Forty

## What is this product?

A construction company can only bid on ~3 of the ~40 public tenders published every
week. Someone has to read every "Leistungsverzeichnis" (bill of quantities, LV) by
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

Requires **Python 3.11+** and a Gemini API key.

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env` (never commit this file):

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
```

Start the server:

```bash
uvicorn app.main:app --reload --port 8000
```

- Health check: `curl http://localhost:8000/health` → `{"status": "ok"}`
- Interactive API explorer: <http://localhost:8000/docs>

### Try the extraction API directly

```bash
curl -sS -F 'file=@/path/to/tender.zip' http://localhost:8000/api/extractions
# → {"id": "...", "status_url": "...", "audit_url": "...", "data_url": "..."}

curl -sS http://localhost:8000/api/extractions/<id>          # poll job status
curl -sS http://localhost:8000/api/extractions/<id>/data     # 12 extracted fields (JSON)
curl -sS http://localhost:8000/api/extractions/<id>/audit    # source evidence per field
```

Run it together with the frontend (`npm start` in `../frontend`, served at
`http://localhost:4200`) for the full demo: upload a ZIP, watch progress, preview
and download the extracted JSON.

### Run the extraction as a standalone script

```bash
python scripts/extract_tender.py path/to/tender.zip
```

See [`scripts/EXTRACTION.md`](scripts/EXTRACTION.md) for offline replay fixtures,
all-page processing details, and audit output.

### Run tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Tests cover multipart upload, PDF parsing, Gemini title selection, progress
tracking, retries, capacity limits, CORS, and the OpenAPI schema, using a fake
Gemini transport (no live API calls / cost).

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

- **Extraction only, end to end.** The live API path is
  `upload ZIP → Gemini extraction → 12 JSON fields`. It does **not** apply the
  hard filter or produce a bid/no-bid verdict yet — `app/filters/hard_filter.py`
  and `app/llm/reasoning.py` exist and are tested, but are not called by
  `app/api/extractions.py`.
- **No company profile input.** Extraction results are per-document, not
  matched against a company's capabilities.
- **Single-process, in-memory jobs.** Extraction jobs and results live in
  memory for one hour and are lost on restart. Run exactly **one** Uvicorn
  worker — this is a local, single-user demo setup, not a production
  deployment (no auth, no persistent/shared job storage).
- **Upload limits.** 50 MiB max ZIP size, 200 PDFs max, 250 MiB max
  uncompressed PDF data per archive.
- **Image-only pages need OCR.** Genuinely blank pages are skipped
  automatically; non-blank scanned/image-only pages that can't be read fail
  extraction with an explicit error rather than silently guessing.
- **No fetch pipeline wired to the API.** The `oeffentlichevergabe.de` fetch
  script and platform adapters (`app/fetch/`) exist for building a tender
  dataset offline, but are not exposed as an endpoint.
