# TripRadar implementation and acceptance status

The four OpenAI-backed agents are implemented: Orchestrator, Itinerary-Builder, Price-Watcher,
and Weather-Risk. Runtime grounding verification, schema repair and a separate offline judge
also use OpenAI. `LLM_MODEL` applies across roles unless an explicit role override is configured.
The ingestion embedding model remains Chroma's local MiniLM; it is not an agent LLM.

This document distinguishes implemented code from live-provider and human acceptance. It does
not certify that every real request produces a complete itinerary or that the judge is accepted.

## Implemented paths

| Area | Implementation | Behavior and limits |
| --- | --- | --- |
| UI/API | `ui.py`, `api.py` | Streamlit submits only to FastAPI; structured validation, session capabilities, idempotency, polling and explicit errors precede/contain agent work |
| Four agents | `runtime.py`, `llm.py`, role prompts | DeepAgents registered delegation, bounded history, OpenAI JSON output and strict serial tool binding; domain reads are application-bound MCP calls |
| RAG | `mcp_server.py` | Explicit Cloud/local selection, city scope, existing 384-dimensional embeddings, up to 12 chunks; no silently created collection or Cloud-to-local fallback |
| Flight/hotel prices | `providers.py` | Read-only Amadeus OAuth, flight search, hotel-ID lookup and hotel offers; test/production provenance, total scope, exact origin and fixed arrival dates validated |
| FX/budget | `ledger.py` | ECB-scoped Frankfurter rates, date/direction/freshness checks, Decimal rounding, unique cost categories, evidence IDs and application-issued user allowances |
| Reconciliation | `ledger.py`, `runtime.py` | Reserve arrival/departure days, exclude conflicting activities, inspect hotel location/check-in, bounded hotel repricing and final weather/budget recomputation |
| Weather | `providers.py`, `ledger.py` | Actual returned local dates, fresh observations, >=60% rain heuristic, evidenced indoor/outdoor/unknown exposure, nullable conflicts |
| Grounding | `grounding.py` | Exact claim/source hashes, one decision per claim, bound support spans, batched OpenAI verification; failure blocks affected claims |
| Recovery | `recovery.py`, `llm.py` | One schema repair and one grounding repair within two shared recovery episodes; bounded optional weather revision; one transient model retry, at most two transient provider-read retries |
| Persistence | `store.py` | SQLite atomic terminal result/artifacts/history; restart interruption of queued/running requests; explicitly scoped allowance reuse; independent evaluation evidence |
| Observability | `observability.py`, `langsmith_export.py` | One queued rotating log writer, prompt/tool definitions referenced by hash, 14-day backup retention, redaction, optional sanitized LangSmith export |
| EDD | `evaluation.py` | Immutable capture, explicit human review/adjudication commands, offline OpenAI judge, per-agent/criterion metrics, family-level acceptance checks and confidence intervals |
| Tracking | `tracking.py` | Acceptance-gated 10% sampling, completion-transaction outbox, one worker, USD 1/job and USD 10/day conservative reservations; no agent-answer or policy mutation |
| Retrieval evals | `retrieval_evaluation.py` | Passage precision and capacity-checked evidence-group recall; reviewed <=k witnesses; explicit unsupported-query abstention |
| E2E harness | `evaluation.py baseline`, `evals/e2e_cases_v1.json` | Twenty development scenarios; capture all terminal outcomes, including failures; never pass expected behavior into model context |

The application enforces tool permissions, record scope, budget arithmetic and final rendering.
Semantic support remains a fallible model judgment. A valid citation/hash is not itself proof of
support. Only accepted claims appear in rendered activities. Missing required coverage produces
partial/unknown results. A complete planning result still does not book travel or guarantee future
availability, weather, safety or actual expenditure.

## Start and configure

From the project root:

```bash
uv sync
PYTHONPATH=src .venv/bin/python -m tripradar_agents.cli
```

UI: http://127.0.0.1:8501. API readiness: http://127.0.0.1:8000/ready.
The launcher starts both services; the runtime starts/closes four isolated stdio MCP domain
processes when needed. Separate MCP terminals are not necessary. One API worker owns the SQLite
runtime and log stream. Shared Streamable HTTP MCP hosting is not implemented; stdio preserves
the existing client/server isolation without adding externally exposed tools.

Configure your ignored `.env` using `.env.example`. Keep OpenAI settings as already configured.
For Amadeus add `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` and
`TRIPRADAR_AGENT_AMADEUS_ENVIRONMENT=test` or `production`. Test is the default, and is displayed
as test data even when the application/LLM run in live mode. Missing credentials permit an
unpriced partial plan. No credentials were copied from chat into configuration.

`/ready` distinguishes missing settings from configured-but-unverified pricing. Optional
`TRIPRADAR_AGENT_STARTUP_MODEL_PROBES=true` checks OpenAI model visibility at startup with read-only
requests. It is not proof of tool-call quality or a successful paid completion.

Enter outbound flight date in the origin's local date and destination itinerary dates separately.
A flight arriving after the fixed first destination day is ineligible. Hotel offers preserve their
quoted whole-stay/whole-party basis; repeated alternatives cannot be added together. Uneven adult
allocation across rooms remains explicitly unsupported until room-level allocations can be
verified; it is never guessed. No package, child/infant, accessibility or booking guarantees are made.

Optional spending allowances are explicit whole-trip amounts in the chosen currency. Checked
submission creates application-owned acceptance records; the LLM cannot approve them. Unchanged
trip scope can reuse earlier allowances; changed scope requires new explicit acceptance. The clear
allowances option revokes reuse. An allowance for unpriced mandatory fees is an accepted estimate,
not proof those fees were quoted. A fit verdict using allowances is conditional and may differ
from actual expenses. Missing FX or mandatory cost coverage leaves the full total unknown; a
known lower bound can still establish over-budget.

## EDD workflow

Capture a terminal UI request using its request ID:

```bash
PYTHONPATH=src .venv/bin/python -m tripradar_agents.evaluation capture \
  --database data/runtime/tripradar.sqlite3 --request-id REQUEST_ID \
  --output data/evals/review-v1 --case-id TR-ORCH-002 --family-id lisbon-budget-family
```

Use the actual matching case ID and family lineage. The command creates hashed response/evidence
snapshots, capture rows and empty human-review templates. Existing captures cannot be overwritten.
The runtime database/logs and benchmark exports stay outside destination Chroma. Export is an
explicit local operator action; benchmark retention must be reviewed separately from runtime
purging. Do not edit snapshots to improve scores.

For development protocol runs:

```bash
PYTHONPATH=src .venv/bin/python -m tripradar_agents.evaluation baseline \
  --cases evals/e2e_cases_v1.json --output data/evals/protocol-baseline-v1 --repetitions 1
```

Without `--live`, this uses a scripted model and synthetic tools, clearly labeled fixture. For
an authorized live B0, review/freeze the cases and provider configuration first, choose a new
output directory, add `--live`, and use three repetitions. That command makes real model/provider
requests. A terminal `completed` status is not a golden-case pass. The harness freezes outputs and
latencies but deliberately does not manufacture human scores.

Review `rubric_v1.json`, preserve version lineage and set its status to `frozen` only after review.
Use the `review` command or edit the CSV templates to record each actual human review. `adjudicate`
requires two distinct reviewer IDs, matching snapshots/criterion/rubric, a named adjudicator,
explicit reference label and rationale. Local reviewer IDs are operator assertions, not an
enterprise identity-verification system. Use `--help` for exact arguments. Semicolon-separated
source review IDs must be shell-quoted.

```bash
PYTHONPATH=src .venv/bin/python -m tripradar_agents.evaluation judge \
  --root data/evals/review-v1 --rubric data/evals/review-v1/rubric_v1.json --split calibration

PYTHONPATH=src .venv/bin/python -m tripradar_agents.evaluation metrics \
  --root data/evals/review-v1 --judge-run-id JUDGE_RUN_ID --split calibration
```

The judge gets the request, exact response, evidence and criterion; human reference labels/reasons
are excluded. Scores use failure as the positive class. Binary precision/recall/F1 exclude
nonbinary decisions and report coverage, errors, critical misses and failure-detection coverage
separately. Undefined denominators stay null. Metrics are written separately per agent/criterion;
judge reliability is not the same as agent task performance. Retrieval metrics require separately
reviewed passage/group labels. New agent outputs need new human review for reliability measurement.

Use `acceptance --help` after calibration and a separate protected judge-holdout run. Acceptance
requires reviewed samples, family separation, per-agent/per-criterion gates and zero critical misses;
insufficient data blocks acceptance. Reports include family-cluster bootstrap confidence intervals.
No accepted profile is supplied with this repository.

Background tracking defaults off. Only after acceptance set
`TRIPRADAR_AGENT_JUDGE_ACCEPTANCE_PATH` to the generated report and
`TRIPRADAR_AGENT_JUDGE_TRACKING=true`, then restart. A stale/missing report disables background work
without taking down trip planning. Pending judge jobs survive restart; running jobs become
interrupted and are not automatically re-billed. Monitoring results are estimates requiring human
follow-up; they never become reference labels or alter system prompts automatically.

## Acceptance still required

- Amadeus environment/credential confirmation and real account/API checks. No live price response
  was used to certify this implementation. Public provider specs and mocked wire responses support
  the adapter tests; test data is never a production quote.
- Real OpenAI + Chroma + weather/pricing end-to-end runs, including latency/cost and itinerary
  relevance. Local tests do not guarantee a ten-day trip will have sufficient relevant evidence.
- Human review/freeze of the 80 existing agent cases, 20 new development E2E cases, retrieval
  evidence groups and semantic-verifier claim pairs. No human labels were invented.
- Independently curated protected agent/judge holdouts. Development cases visible during this
  implementation are not protected holdouts.
- Actual response reviews, judge calibration/acceptance and an operational release decision.
  Continuous tracking remains off until those conditions are satisfied.

The runtime remains bounded rather than exhaustive: 12 model attempts, 20 read-budget units,
120 seconds, 80k conservative input-byte token reservations and 20k output-token reservations.
Provider HTTP attempts are counted within the MCP envelope; a lost envelope retains a conservative
read reservation. Chroma library-internal behavior and model downloads are not certified as
individual provider attempts. Models reserve 1,000 output tokens for extraction/routing/selection,
4,000 for itinerary/repair, and 3,000 for verification. Optional revisions can be skipped when
required validation consumes capacity. MCP transport is stdio, not the plan's eventual shared HTTP
transport. These are explicit implementation limits, not claimed full production readiness.

## Validation and provider references

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python evals/validate_fixtures.py
```

Unit/integration tests cover real framework/MCP execution with fixture providers and mocked OpenAI,
Amadeus and FX wire responses. They include monetary scope/duplicates/staleness, source hashes,
arrival/weather conflicts, bounded recovery, capture immutability, retrieval capacities and judge
queue transactions/caps. Tests do not establish live account access or human acceptance.

Provider implementation references: [Amadeus flight schema](https://github.com/amadeus4dev/amadeus-open-api-specification/blob/master/spec/json/FlightOffersSearch_v2_swagger_specification.json),
[Amadeus hotel schema](https://github.com/amadeus4dev/amadeus-open-api-specification/blob/master/spec/json/HotelSearch_v3_swagger_specification.json),
[Frankfurter](https://frankfurter.dev/), [Open-Meteo](https://open-meteo.com/en/docs).

### Validation performed for this change

- 77 automated tests passed; one upstream Starlette/AnyIO deprecation warning remains.
- All 80 existing fixture-definition checks passed. These checks do not execute agents.
- Twenty fixture-mode API → agent → MCP protocol runs completed. The corrected export contains
  68 response rows with unique nonempty IDs and verified response/evidence hashes, and zero human
  reviews. See `data/evals/validated-protocol-v1/baseline.json` and its `review/` directory.
- Earlier `implementation-smoke-*` exports are marked invalid for human labeling because of the
  prototype CSV BOM issue. Use the corrected export above. No captured response was relabeled as
  correct and no synthetic record was written to destination Chroma.
- Ruff, whitespace checks and the offline dependency lock validation passed.

The configured OpenAI key is present and all current agent models resolve to `gpt-4o-mini`.
Amadeus credentials are absent; its configured environment defaults to test. Background judging
is disabled. No live account/provider completion or human acceptance is claimed by these checks.
