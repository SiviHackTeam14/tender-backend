# Expose Gemini tender extraction through an upload API and Angular client

## User story

As a frontend engineer, I want to upload a tender ZIP and receive progress,
structured requirements and source evidence, so the tender detail UI can show
real requirements without handling Gemini credentials or waiting on a long request.

## Acceptance criteria

- [x] Evaluate every PDF filename before opening selected PDFs; retain include/exclude decisions and reasons.
- [x] Process all pages of selected PDFs using bounded chunks with Gemini 3.8 Flash.
- [x] Unknown values remain null; role is main_contractor, subcontractor, or null.
- [x] Invalid model JSON/schema output is retried once, then fails explicitly.
- [x] Combine trade/reference descriptions and retain their individual source findings.
- [x] Distinguish missing values from unresolved scalar conflicts in API responses.
- [x] POST a ZIP to `/api/extractions`, return 202 and a job ID, and expose progress/result/error through polling.
- [x] Provide typed Angular interfaces and an upload/polling service.
- [x] Test success, failure, title exclusion, progress, capacity, cleanup, CORS and OpenAPI.
- [ ] Review and merge the backend and frontend pull requests together.

## Scope

Backend: extractor, title-selection pipeline, in-process jobs, FastAPI routes,
source audit, regression tests and integration documentation.

Frontend: extraction interfaces, ExtractionService and HttpClient provider.
The final upload/detail UI is owned by the upcoming frontend work.

## Validation

- Backend: 44 tests passed, one opt-in live Gemini test skipped in the regression suite.
- Angular development build passed.
- Earlier live Gemini 3.8 Flash test: 24 PDF titles reviewed, 17 selected, 127 pages
  processed in 32 chunks. Completion date matched the source (2026-12-18).
- Saved real Gemini chunks were re-merged successfully with the new text aggregation.
- Existing frontend scaffold test fails on missing `src/app/models/.gitkeep`;
  the service and application compile successfully.

## Integration limits

Run one backend process. Jobs/results are in memory for one hour and disappear on
restart. Two concurrent jobs; at most 20 retained jobs. The local demo has no
application authentication or durable/shared queue. Title filtering and PDF text
extraction do not guarantee full-package coverage. Free-text aggregation preserves
claims without proving their logical compatibility.

## Related work

Extends the extraction prompt story (Story 2.1) and provides an integration boundary
for Story 1.2. See `scripts/FRONTEND-INTEGRATION.md` and `scripts/EXTRACTION.md`.
The downloaded real tender ZIP remains local; the live test requires supplying it.
