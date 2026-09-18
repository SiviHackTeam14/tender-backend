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
