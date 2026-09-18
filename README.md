# tender-backend

FastAPI backend for the tender triage tool.

## Setup

Requires Python 3.11+.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

Server starts at `http://localhost:8000`.

## Health check

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

## Layout

- `app/main.py` — FastAPI app, CORS, `/health`
- `app/models.py` — placeholder (real models land in Story 0.2)
- `app/api/` — route modules (Story 3.2)
- `app/filters/` — `hard_filter` (Story 3.1)
- `app/llm/` — Gemini client (Epic 2)
- `app/data/` — JSON fixtures (Story 0.3)
- `scripts/` — standalone scripts (e.g. `prototype.py`)
- `tests/` — empty for now; a test suite lands with a later story

## Scripts

```bash
python scripts/prototype.py
```

Create `.env` with `GEMINI_API_KEY` and `GEMINI_MODEL=gemini-3.8-flash`. Never commit `.env`.

## Tender extraction prototype

See [scripts/EXTRACTION.md](scripts/EXTRACTION.md) for live Gemini extraction,
three offline replay fixtures, all-page processing, audit output, and tests.

## Frontend extraction API

ZIP uploads and polling are available at `/api/extractions`. Start the backend with
`uvicorn app.main:app --port 8000` (one worker) and open `/docs` for the API explorer.
See [frontend integration guide](scripts/FRONTEND-INTEGRATION.md) for the Angular
service, API contract, result statuses, setup and deployment limits.
