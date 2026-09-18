# Bid reasoning (Story 2.2)

`app/llm/reasoning.py` evaluates hard-filter survivors and returns
`list[app.models.TenderAnalysis]`, matching the existing frontend analysis model.
It does not run the hard filter or expose an HTTP route; Story 3.2 should call it
after filtering and combine its results with deterministic rejects.

## Integration

```python
from app.llm.reasoning import analyze, ReasoningError

# profile: CompanyProfile; survivors: list[Tender]
try:
    analyses = analyze(profile, survivors)
except ReasoningError as exc:
    # Surface a controlled job/API error; do not replace it with fabricated decisions.
    raise
```

Set `GEMINI_API_KEY` and optionally `GEMINI_MODEL` in the server environment.
The default is `gemini-3.8-flash`. The CLI loads the backend `.env`; the library
does not load files or make calls at import time. This is a synchronous function;
an async FastAPI handler should run it in a worker/thread.

Story 2.3 may supply `analyze(profile, survivors, generate=client)`, where
`client(prompt: str, schema: dict) -> str` returns model text. The complete prompt
contains the policy. Configure `SYSTEM_PROMPT` as the transport's system instruction
as well; the default Gemini client does this using Google's documented
[`systemInstruction`](https://ai.google.dev/api/generate-content#request-body).
No scores, ranking fields or similarity-based recommendations are allowed.

For a caller owning its own retry loop, use `build_reasoning_prompt`,
`reasoning_response_schema` and `parse_reasoning_response(raw, expected_ids)`.
Do not add another malformed-output retry around `analyze`: it already retries
exactly once and then raises `ReasoningValidationError`. Validation includes strict
JSON, duplicate JSON keys, all five criteria, no extra fields, concise one-line
sentences, exact ID coverage and verdict/status consistency. Response ordering is
normalized to input ordering. Formatting checks do not prove semantic accuracy;
source-grounded review is still needed for model quality.

`ReasoningInputError` indicates invalid caller input/configuration.
`ReasoningTransportError` wraps Gemini/requests failures without including secrets
in its public message. Transport retries and caching belong to Story 2.3; this
function does not retry network errors. It returns no partial results on failure.
Empty survivor lists return `[]` without needing credentials or spending tokens.

## Decision policy

The story title and first acceptance criterion differed on REJECT; the product
decision is to **allow REJECT for definite blockers and use MAYBE for missing
information**. All five criteria always receive a reason:

| Condition | Verdict |
| --- | --- |
| Any criterion is BLOCK, backed by an explicit incompatibility | REJECT |
| No BLOCK, but reference, financial, regulatory or strategic criterion is WARNING | MAYBE |
| Those four criteria PASS; competitive position is PASS or WARNING | BID |

Unknown competitor counts alone do not prevent BID. Missing reference counts,
dates, amounts, qualifications or crew capacity are not invented. A profile's
explicit inability is distinguished from an absent reference/certificate entry.
`hard_reject_reason` stays null for these LLM results, including REJECT; the blocker
is explained in `summary` and `criteria`. Hard-filter rejects are owned by the caller.

The compact prompt includes all requested tender fields, plus `complexity_markers`,
and uses `construction_window: {start, end}`. It preserves nulls, restrictions and
self-performance requirements. Distances come from the matching Augsburg/Plauen
field based on the company's location. For any other base supply
`distances_km={tender_id: distance, ...}`; no wrong-base fallback is made.
Role values are `main_contractor`, `subcontractor` or null. The legacy fixture's
`either` value and its fixture generator have been migrated to null.

## Try it

From `tender-backend`, with its dependencies installed:

```bash
python scripts/reason_tenders.py \
  --profile-id profile-a \
  --tenders tests/fixtures/reasoning/comparison-tenders.json \
  --model gemini-3.8-flash

python scripts/reason_tenders.py \
  --profile-id profile-b \
  --tenders tests/fixtures/reasoning/comparison-tenders.json \
  --model gemini-3.8-flash
```

Use `--dry-run` to inspect the prompt without a model call and `--output PATH` to
save the response. For another company base, `--distances PATH` reads a JSON object
mapping tender IDs to distances. The CLI expects a JSON array of shared `Tender`
objects already selected by the caller's hard filter, not raw extraction fields.

The comparison file contains **three synthetic tenders**, adapted from the shared
sewer, school and high-voltage fixtures, using the unchanged shared company
profiles. Synthetic distances, contract values, dates and neutral roles let both
profiles pass the five planned hard checks; these are not real travel distances.
Their reference requirements deliberately specify no unproven count/lookback
thresholds. Expect sewer references to favor A, school references to favor B,
and B's explicit high-voltage exclusion to cause REJECT. Missing evidence for A's
electrical capability should cause review, rather than an invented qualification.
The precomputed `app/data/analyses.json` is not supplied to the model: it contains
authored demo outcomes, not evidence for a new decision.

## Verification

```bash
python -m pytest tests/test_reasoning.py -q
RUN_GEMINI_REASONING_TEST=1 python -m pytest tests/test_reasoning_live.py -q -s
```

Offline tests use fake transports to check validation and integration, not LLM
quality. The opt-in test makes real Gemini calls for both profiles against the
same three tenders, saves the full responses under pytest's temporary directory,
and checks reference differences and the explicit high-voltage blocker. Review
those saved reasons against the inputs rather than relying only on passing tests.

The 2026-09-18 live run was inspected against both profiles and all three mock
tenders; its actual outputs are saved in
[`gemini-3.8-flash.sample.json`](../tests/fixtures/reasoning/gemini-3.8-flash.sample.json).
The final run produced:

| Synthetic tender | Profile A (civil works) | Profile B (electrical) |
| --- | --- | --- |
| Sewer renewal | BID: matching sewer references | MAYBE: sewer references and delivery capability unconfirmed |
| School electrical fit-out | MAYBE: electrical references and delivery capability unconfirmed | BID: matching school references and trade |
| High-voltage substation | MAYBE: references, qualification and capability unconfirmed | REJECT: high voltage explicitly excluded |

All six outputs contained five criteria, one-sentence reasons and no similarity
scores. Financial reasons used the supplied EUR 600,000 value and EUR 50,000
guarantee against each profile's different limits. Unknown competitor data was
acknowledged rather than fabricated. These snapshots illustrate model behavior;
they are not fixed expected responses or a claim of independently verified facts.
