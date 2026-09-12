# Generate TripRadar Application Details, Design and Technical Architecture Documentation

## 1. Assignment and scope

Create a complete, evidence-based **TripRadar — Application Details, Design & Technical Architecture** document for the current repository, `AgenticAI_MAI-Final-Project`.

Subtitle: **Multi-Agent Travel Planning with Source-Grounded Itineraries, Pricing and Weather Evidence**.

Explain the business purpose, traveler experience, ingestion subsystem, agent runtime, data contracts, security, observability, evaluation lifecycle and operational procedures as one connected application. Write for project reviewers, developers, operators and a reader preparing a demonstration or technical handoff.

This file is a **reusable documentation-generation prompt**. When asked to edit this prompt, edit only the prompt. Execute the document-generation assignment only when the user asks to generate the documentation. Generating documentation does not authorize implementing missing features, changing configuration or datasets, submitting paid requests, publishing documents, or uploading private evidence.

The earlier project's application-document prompt is a reference for coverage, structure and presentation only. Do not copy its prose, architecture, feature claims, code, counts, screenshots, business workflows or provider choices. This project concerns travel planning, not healthcare, registration for care recipients, case management or simulated service bookings.

## 2. Mandatory accuracy and evidence rules

Before writing, inspect the current repository. Treat runnable code and validated artifacts as implementation evidence; treat design plans as intended behavior. Where these disagree, document the discrepancy rather than silently selecting the more complete design.

Use these feature labels consistently:

- **Implemented:** a concrete code path exists; separately state how it was tested.
- **Partially implemented:** describe the working path and exactly what remains unavailable.
- **Planned / future enhancement:** a design or requirement exists without a working implementation.
- **Not verified:** evidence does not establish execution, correctness or external availability.

“Implemented” does not mean tested against a live provider. Keep these evidence categories separate: source inspection, offline unit tests, real local protocol integration, scripted fixture execution, mocked provider responses, live provider calls and human-reviewed evaluations.

Include this project outcome statement, clearly labeled as the **target**, not a measured accomplishment:

> TripRadar aims to turn an explicit destination, date range and budget into a useful day-by-day trip plan, with recommendations supported by retrieved destination guidance, costs supported by current offer evidence, weather risks aligned to travel dates, and an honest budget verdict that preserves uncertainty.

Do not invent numerical success claims. Report targets, measured values, sample sizes, evaluation dates, pass/fail/inconclusive outcomes and skipped checks separately. Do not copy old test counts or corpus counts as current measurements.

Maintain a compact evidence register:

| Claim / capability | Status | Repository file and symbol or artifact | Evidence date/version | Validation type | Limitation |
| --- | --- | --- | --- | --- | --- |

Cite repository-relative paths and actual function/class names. Check links before delivery. External SDK/model/pricing claims require current official sources if included; account access and provider uptime require actual authorized verification. A provider's documentation is not proof that this account can use that provider.

## 3. Source inventory and conflict reconciliation

Read and reconcile these project sources when present:

1. `README.md`, `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore` and applicable repository instructions.
2. `prompts/DataIngestion.md` and `prompts/DeepAgentsImplementation.md`, including implementation-status and provider-correction notes.
3. `Trip-Planner-prompts/AGENTS.md`, `IMPLEMENTATION.md` and `TRIPRADAR.md` as design references. Their older model/provider and date examples must not override current code or accepted corrections.
4. `docs/agents/vertical-slice.md`, `docs/chroma-cloud.md`, `docs/ingestion-operations.md`, `docs/ingestion-observability.md`, `docs/source-attribution.md` and `docs/validation.md`.
5. All maintained modules in `src/tripradar_ingestion/` and `src/tripradar_agents/`.
6. `config/settings.yaml`, `config/destinations.yaml`, `config/prompts/` and `config/security/`.
7. Canonical golden CSVs, companion JSON/manifest, fixture index and validator, review templates and any subsequently implemented evaluation code/reports.
8. Relevant unit/integration/UI/provider-adapter tests and their fixtures.
9. Sanitized, authorized manifests and validation summaries, if needed to establish corpus or run status. Prefer summary artifacts over raw logs or database dumps.
10. Any existing application documentation, diagram source or screenshots, after confirming their date and consistency with code.

Do not read or reproduce `.env`, credentials, session capabilities, private conversations or unrestricted request artifacts as documentation inputs. Document configuration from `.env.example` and settings code. If runtime configuration must be checked, inspect only allowlisted nonsecret names/values or boolean presence, never dump the environment.

Explicitly resolve likely contradictions: ingestion-only wording in an older README versus existing agent code; full target architecture versus the smaller implemented slice; outdated provider references versus the OpenAI-only runtime; shared HTTP MCP design versus current stdio transport; empty review templates versus completed human evaluation; and LangSmith configuration versus confirmed export.

If a referenced source is absent, record it as unavailable. Do not create missing application modules or treat an IDE tab name as proof a file exists.

## 4. Deliverables for the later documentation-generation task

Create a maintained Markdown source and matching rendered documents:

```text
docs/application/TripRadar_Application_Design_Technical_Architecture.md
docs/application/TripRadar_Application_Design_Technical_Architecture.docx
docs/application/TripRadar_Application_Design_Technical_Architecture.pdf
```

Store editable diagram sources and rendered figures under `docs/application/figures/`. Include a short evidence/validation appendix in the document and a generation note listing actual outputs, conversion tools and rendering checks. These are future output targets; editing this prompt alone must not generate them.

Use the author **Kabilan Subramaniam**, the actual document-generation date, inspected repository revision and a note about uncommitted changes if applicable. Do not hard-code the date or claim a clean revision when it is not clean.

Required presentation: professional cover, linked table of contents, numbered sections, glossary, readable typography, captions and numbering for tables/figures, page numbers and headers/footers in rendered formats. Use landscape pages for wide diagrams when helpful. Preserve image aspect ratios, readable labels and source attribution. Keep figures with captions; avoid shrinking diagrams to unreadable sizes to fill leftover space.

If DOCX/PDF tooling is unavailable, still produce the Markdown and editable diagrams, and explicitly report which formats were not generated. Never provide fake download links or claim conversion/visual inspection that did not occur.

## 5. Cover, glossary, executive summary and introduction

Explain the traveler problem: destination research, organizing activities across dates, uncertain costs, mismatched arrival assumptions, weather coverage and fragmented evidence. Introduce budget-conscious travelers, multi-person trip planners, application operators and human evaluators as relevant personas; do not imply account registration or multi-user production identity exists.

Explain the target UC1: **“Plan a 10-day trip to Portugal in October, budget $2,000.”** Identify why this request is incomplete: city scope, year/exact dates, origin airport, party/room details, currency and budget scope may need clarification. Lisbon coverage is not nationwide Portugal coverage. Show how an explicit single-city request differs from the broad natural-language request.

State the four initial destination corpora: Lisbon, Paris, London and New York City, with only the districts/boroughs actually collected. Explain that the UI's current supported fields and the natural-language parser's supported inputs may differ from the final target.

Glossary must define: agent, orchestrator, specialist, DeepAgents, LangGraph, LangChain, LLM, MCP, stdio, Streamable HTTP, tool discovery, tool allowlist, RAG, embedding, vector database, Chroma, MiniLM, cosine distance, source revision, grounding, semantic support, guardrail, prompt injection, evidence ID, validated state, idempotency, transaction, SQLite/WAL, fixture, EDD, golden dataset, B0 baseline, human adjudication, holdout, LLM-as-judge, precision/recall/F1, evidence-group recall@k, observability, LangSmith and trace correlation.

Use relevant, locally available travel imagery only when appropriate and licensed. Do not assume an `images/` folder or a maintained architecture screenshot exists. If no suitable images exist, use original technical diagrams rather than inventing screenshot evidence. Label illustrative figures as illustrations.

Immediately after the introduction, place a readable **Overall Application Overview** figure on its own page in the rendered documents. Show the actual source-to-response path and separately indicate deferred provider/reconciliation branches. Do not reuse a diagram whose process boundaries or capabilities belong to another project.

## 6. Goals, non-goals and implementation status

Provide a feature matrix covering ingestion, local embeddings, local/Cloud Chroma, runtime retrieval, four agents, UI/API, MCP, request validation, history, evidence persistence, budget logic, weather, logging, LangSmith, fixtures, human review and automated evaluation.

Recheck these current reference checkpoints against code at generation time:

- The ingestion pipeline is implemented; a guarded UI/API/agent/MCP slice also exists.
- Fixture mode runs the real graph/protocol path with a scripted model and synthetic operational results. It is not a live LLM itinerary-quality test.
- The fixture itinerary currently selects one archived passage-derived activity for the first day. Empty remaining dates are a fixture limitation, not evidence of missing Chroma records.
- Live guide retrieval and a limited rain-probability forecast adapter exist. Availability and quality still require verification.
- Live flight/hotel pricing is unavailable in the slice; synthetic amounts are not live offers.
- Complete budget coverage, live FX, accepted allowance workflows and offer/logistics reconciliation remain target capabilities unless subsequent code implements them.
- Outputs are provisional/partial; the code does not establish a complete ten-day itinerary or all-weather safety.
- Automatic repair/security-learning loops, protected evaluation populations, judge automation and continuous quality scoring remain distinct from implemented validation and observability.

Non-goals include making bookings/payments, promising availability, issuing official weather alerts, autonomous outbound notifications and guaranteed safety. Describe future multi-city planning as a roadmap item unless implemented.

## 7. System architecture and required diagrams

Describe two cooperating packages:

```text
tripradar_ingestion = collects, normalizes, embeds, validates and publishes attributed destination knowledge
tripradar_agents   = UI/API, guarded LLM orchestration, specialist/MCP work, evidence validation and runtime state
```

Keep the parent project root as the implementation boundary. `Trip-Planner-prompts/` contains reference documents, not a separate deployed application or package root.

Include these distinct diagrams with legends:

1. Current system context: traveler, UI, API, model provider, MCP subprocesses, guide store, weather source, optional LangSmith and local artifacts.
2. Ingestion flow: source registry → Wikivoyage → raw preservation → parse/clean/normalize → chunk → local embeddings → validate/publish → local/Cloud retrieval.
3. Actual user-request sequence, including extraction, validation, ordered specialist execution, claim checking, budget calculation, persistence and UI polling.
4. Process/deployment view: Streamlit and FastAPI ports, request-scoped stdio MCP processes and their lifecycle. Show future shared HTTP MCP servers separately.
5. Trust boundaries and data stores: untrusted text/proposals versus application-owned constraints/evidence; Chroma versus SQLite versus logs/evaluation files.
6. Evaluation lifecycle: plan → curate/version golden data and choose metrics → baseline → monitor errors → refine → calibrate/validate judge → continuous tracking → reviewed improvements.

Prefer Mermaid or another editable diagram format for technical diagrams; embed rendered versions in DOCX/PDF. Mark planned nodes and unavailable evidence clearly. Do not imply all specialists run in parallel if the current implementation enforces order.

## 8. Mandatory user-query runtime flow — file by file

Provide a numbered call-path walkthrough, with actual symbols verified from source. Distinguish once-per-process initialization, once-per-request work, per-model dispatch, per-tool subprocess creation and background telemetry export.

At minimum cover:

| File | Detail to explain |
| --- | --- |
| `src/tripradar_agents/cli.py` | Launcher, mode selection, environment propagation, UI/API child processes, loopback ports and shutdown |
| `src/tripradar_agents/config.py` | Configuration loading, shared/provider/role precedence, rates, caps and readiness |
| `src/tripradar_agents/ui.py` | Form submission, client-message ID retention, API-only access, polling, readiness/error display and response rendering |
| `src/tripradar_agents/api.py` | `create_app`, lifespan, request bounds, authorization, admission, scheduling, terminal handling and endpoint contracts |
| `src/tripradar_agents/store.py` | Session capabilities, idempotency, active-request uniqueness, history, transactions, restart and deletion |
| `src/tripradar_agents/runtime.py` | `Runtime.run`/`_run`, extraction, application validation, registered specialists, evidence joins, verification and fixed response construction |
| `src/tripradar_agents/llm.py` | `create_model`, `run_agent`, `Boundary`, filtered catalogs, actual model dispatch and explicit `FixtureModel` behavior |
| `src/tripradar_agents/security.py` | Redaction, input rules, `normalize`, `Budget` and deterministic activity/evidence checks |
| `src/tripradar_agents/models.py` | Typed request/proposal/activity/selection/support contracts and inclusive date calculation |
| `src/tripradar_agents/mcp_client.py` | `ALLOW`, `call_mcp`, application-bound context, initialize/list/call lifecycle, result handling and cleanup |
| `src/tripradar_agents/mcp_server.py` | Domain server selection and actual guide, price, weather and calculator implementations |
| `src/tripradar_agents/observability.py` | Request-scoped trace buffering, local logging and exporter handoff |
| `src/tripradar_agents/langsmith_export.py` | Sanitized RunTree hierarchy, bounded background queue, delivery status and shutdown behavior |

Explain how DeepAgents-registered compiled/runnable specialists differ from dedicated classes or separately hosted agent services. Do not invent an `agents/orchestrator.py`, a manually authored `StateGraph`, persistent graph checkpoint service or HTTP tool server if the current source does not contain one.

Describe actual specialist context carefully: original request, permitted history, validated trip, evidence and available tools. Verify whether weather assessment receives itinerary activities; do not describe true activity-specific weather conflict detection if it only reports date-level rain risk.

Show one representative success/partial path, one clarification path and one validation-failure path. A source excerpt is not a completed travel activity schedule; explain how source evidence becomes an accepted recommendation and how unsupported dates remain visible.

## 9. Request, normalization and clarification contracts

Separate raw API request, model-proposed extraction and application-validated trip state. Explain the trust transition and accepted provenance.

Document actual destination, start/end date, budget, currency, origin, adult and room fields; required/optional status; supported bounds and aliases; inclusive trip days versus hotel nights; supported airports; invalid and ambiguous inputs; and whether past-date validation exists. Mark missing validations as limitations rather than assuming them.

Explain the conservative current extraction behavior: structured form values are authoritative, repeated matching proposals need not also occur in prose, numeric `budget`/`adults`/`rooms` proposals are normalized before domain checks, and malformed structures or conflicting proposals remain rejected/clarified. Literal substring matching alone cannot establish affirmative user intent. Describe the accepted `field: value` path and limitations for negation, hypotheticals and natural-language date interpretation.

Use sanitized examples for integer-versus-string proposal handling, differing decimal representations, model/form conflicts and missing travel details. Distinguish `needs_clarification` from malformed HTTP input and from operational failure.

## 10. Agent roles, prompts and tool permissions

Provide an agent matrix with role, configured model, input schema, effective prompt, permitted MCP domain/tool, output schema, deterministic checks, downstream consumer and known limitation.

Cover Orchestrator, Itinerary-Builder, Price-Watcher and Weather-Risk-Agent. Explain that the runtime semantic verifier is a separate tool-free validation service, not a fifth planning specialist or the offline evaluation judge.

Inventory `config/prompts/common_policy.md`, `orchestrator.md`, `itinerary_builder.md`, `price_watcher.md`, `weather_risk.md`, `grounding_verifier.md` and `repair.md`. Explain common-plus-role composition and prompt hashes. A repair prompt existing on disk does not prove an automatic repair loop runs.

Show the shared LLM wrapper's effective input ordering, recent completed exchanges, current request, tool schemas, state/evidence and outputs. Explain that system prompts communicate policy, while application checks enforce schemas, capabilities and constraints. Inspect whether policy YAML is executable configuration or a documented catalog; do not imply automatic rule enforcement from the file's presence.

## 11. MCP architecture and tool contracts

Document actual transport and isolation: `ClientSession`, `StdioServerParameters`, `stdio_client` and `FastMCP`, if these remain the implementation. Describe per-call server startup, fixed domain selection, application-created bootstrap context, tool discovery, allowlist validation and cleanup. Explain that the launcher does not require four extra terminals for this stdio arrangement.

Inventory and verify these current domain tools:

| Domain | Tool | Required documentation |
| --- | --- | --- |
| Destination | `search_guide` | Query validation, application-bound city, fixture/local/Cloud path, returned source metadata |
| Pricing | `search_prices` | Explicit live-unavailable result versus synthetic whole-party/stay fixture data |
| Weather | `get_forecast` | Actual forecast source, dates, probabilities, null/missing coverage and limits |
| Currency/budget | `calculate_budget` | Evidence-ID input, trusted snapshot resolution, Decimal arithmetic and unknown coverage |

Explain source-level function names versus exposed MCP names, actual arguments/results, environment labels, errors, read budgets and timeout behavior. Identify where the application invokes MCP deterministically before a specialist LLM versus where the model proposes a tool call; do not call both autonomous model-selected tool use.

Distinguish validated response envelopes from unrestricted raw provider JSON. Describe why arbitrary model amounts, credentials, destinations, server URLs and evidence-write operations cannot be accepted as authoritative configuration. Shared Streamable HTTP servers, cross-process collectors and optional RAG for every specialist belong in the target view until implemented.

## 12. Destination data collection and ingestion

Explain the real Wikivoyage MediaWiki API, configurable destination registry, canonical titles/aliases and bounded district discovery. Include a credential-free Lisbon API example and attribution/licensing requirements.

Document acquisition limits, identifying User-Agent, request spacing, timeout/retry policy, API errors within HTTP 200, raw revision preservation, checksums, manifests, resumability and `--force`/`--resume` behavior from the actual CLI. Distinguish city root-only collection from all-city/district collection. Do not claim general website crawling, unrelated APIs or arbitrary HTML/PDF support without code evidence.

Walk through collector, parser, cleaner, normalizer, chunker, embedder, vector store, pipeline, manifests, reporting, registry and utility responsibilities. Explain section/listing handling, boilerplate/template treatment, Unicode normalization, deduplication, missing values and unsupported coverage.

Document source metadata: canonical/source/revision/history URLs, destination/section, page/revision identity, retrieval/revision times, content hashes, offsets, attribution and license. Explain revision-linked reproducibility and why guide statements are not current offers or official weather information.

## 13. Chunking, embeddings and Chroma

Verify current chunking defaults and describe their rationale: approximately 180 target tokens, up to 24 overlap tokens and a 256-token embedding input ceiling including contextual prefixes/special tokens, if unchanged. Explain structure-aware boundaries, preserved offsets, short useful warnings and explicit tokenizer checks rather than silent truncation.

Separate the generation LLM from the embedding model. TripRadar uses local Chroma/MiniLM `all-MiniLM-L6-v2` embeddings with 384 dimensions; choosing OpenAI for agents does not change ingestion/query embeddings to OpenAI. Nebius and Actian are historical design alternatives, not current providers.

Explain explicit model setup/download, cache location/checksums, finite/dimension/nonzero vector validation, stable IDs, index generations, active collection manifest, readback before publication, failed-publication rollback and targeted updates preserving other cities.

Distinguish local persistent Chroma from Chroma Cloud. Document explicit backend/collection selection, cloud copy/readback and shared embedding-space compatibility. CloudClient does not expose a local database automatically. Show where generated `.npy` vectors, collection files and manifests reside; do not describe binary vector files as a user-friendly database browser.

Report corpus counts only from a dated verified source, identifying pages/chunks/cities and local versus Cloud scope. Stored-record equality does not establish semantic relevance. Never infer absent guide coverage merely from empty itinerary days.

## 14. Retrieval and grounding

Describe the actual semantic query path, destination/section filtering, top-k limits, returned passage metadata and cosine distance/similarity interpretation. Similarity is not calibrated confidence. Do not claim hybrid retrieval, BM25, reranking or equivalent evidence grouping in the runtime unless implemented.

Separate:

1. deterministic checks: schema, evidence identity, destination, date, numeric fields and exact quote containment;
2. semantic support: whether the cited text supports the full generated claim;
3. external freshness: whether a source is applicable as current information;
4. offline evaluation: independently measuring correctness using human labels and benchmark evidence.

Explain accepted/rejected claims, unfilled days, template rendering and the fallibility of the semantic verifier. Exact quotations and valid citation IDs do not prove a useful itinerary, current truth, safe weather or practical travel logistics. Document what happens on verifier/schema/provider failures and whether bounded repair is actually implemented.

## 15. Pricing, budget, weather and reconciliation

Describe existing behavior first, then the target contracts in a separate subsection.

Budget coverage must distinguish flight/hotel totals, traveler/room/night basis, taxes, currencies, daily spending, transfers, activities, allowances and unknown items. Explain ID-bound evidence resolution, compatible trip scope, duplicate/forged IDs, source timestamps, Decimal arithmetic, rounding, known subtotal versus total and `unknown` versus `over` verdicts. Do not infer `fits` from an incomplete subtotal or from synthetic offers.

The target needs validated offers, application-recorded accepted allowances, internally resolved FX/taxes/occupancy and versioned budget evidence. State which of these exist and which remain unimplemented.

Explain Open-Meteo rain probabilities, destination timezone/coordinates, requested-date filtering, returned forecast horizon, stale/null/out-of-range handling and fixture weather. Low rain risk is not overall safety; rain probability is not an official alert, climate outlook or complete weather-risk assessment.

Explain the planned arrival/departure/hotel reconciliation: selected offers can invalidate independently drafted activities; changed plans require affected logistics/weather/budget rechecks within shared execution limits. Do not present this as implemented when the current output explicitly says logistics are not established.

## 16. Persistence, history, concurrency and lifecycle

Document SQLite path resolution, WAL/foreign keys/synchronous settings, actual tables/indexes, session capability hashing and expiry. Explain how request payload and terminal result represent the user/assistant exchange, rather than inventing separate message tables.

Describe request admission, queued→running claim, completion/error writes, atomic result/history/artifact persistence, per-session active uniqueness, payload-hash idempotency, duplicate replay, busy conflicts and late completion rejection. Explain current queue/concurrency caps and distinction between queue timeout and execution deadline.

Cover the latest ten completed exchanges, whole-exchange trimming, current-message deduplication, trusted trip state versus conversation text, and clarification/partial versus failed/interrupted history. Inspect actual restart and deletion code: queued/running jobs become interrupted rather than invisibly replaying paid work; New trip/session deletion and artifact retention must match implementation.

Distinguish authoritative SQLite state from ephemeral graph state and any future checkpoint/outbox design. Do not claim exactly-once external billing, automatic durable job recovery, distributed workers or transactional coverage the code does not provide.

## 17. Guardrails, security and privacy

Explain checks before every model dispatch, before tool execution and before response delivery. Include JSON/body/text bounds, field ranges, session ownership, prohibited configuration overrides, bounded context, tool catalogs, permitted delegation, redaction, evidence applicability and numeric validation.

Describe how built-in DeepAgents filesystem/shell/general-purpose tools are filtered and denied, and how specialist descriptions cannot replace application-owned trip state. State limits of keyword-based injection detection and false positives. No prompt or model verifier guarantees safety/correctness.

Distinguish the planned **Policy → Guardrails → Detection → Response → Learning** lifecycle from implemented checks and diagnostics. Never claim that the application automatically learns new policies, edits prompts, performs recovery or promotes changes without evidence. Proposed improvements must go through human review and regression evaluation.

Keep API keys, session capabilities, payment information, unnecessary personal data and hidden reasoning out of documents/screenshots. Explain that redaction is heuristic, not general PII anonymization. `.env`, `.venv`, generated runtime data and private review artifacts remain excluded from Git. Provide only clearly synthetic credential placeholders.

## 18. Observability, logging and LangSmith

Describe ingestion observability separately from agent observability, then explain their correlation boundaries.

Verify and show these repository-relative locations:

```text
data/reports/<run_id>/events.jsonl         # ingestion stage events
data/reports/<run_id>.json                # ingestion summary, verify actual layout
data/runtime/logs/application.log         # default live-agent log
data/runtime/fixture/logs/application.log # launcher fixture-mode log
data/runtime/tripradar.sqlite3            # default live request/evidence store
```

Explain configurable database/log locations, actual UTC timestamp format, local rotation ownership/limits, and any unimplemented age-based retention. Do not import another project's timestamp format or claim an external collector exists when only the API process writes logs.

Cover request, agent, LLM input/output/error, tool, RAG and validation events. Explain prompt hashes, source IDs, model/provider/mode metadata, token usage if actually captured, conservative cost reservations and the difference from billed cost. Validation diagnostics should identify schema/stage/field types without copying private failed inputs.

Agent LangSmith uses opt-in redacted post-request export, a bounded worker queue and explicit RunTree hierarchy while raw framework auto-tracing remains disabled. Cover root request → agent → model/tool/retrieval spans; API-boundary MCP tracing is not automatic distributed server instrumentation. Fixture tags must remain visible.

Document `TRIPRADAR_AGENT_LANGSMITH_TRACING`, project `tripradar-agents`, shared `LANGSMITH_API_KEY`/endpoint/workspace and agent-specific overrides. Ingestion uses its own project/settings and may hide inputs/outputs rather than using agent content capture.

Explain `/ready` telemetry status, `langsmith.exported`, `langsmith.degraded`, root readback, trace URL reporting, child visibility lag, missing credentials, queue saturation, network failure and bounded shutdown. **Enabled/configured does not mean uploaded.** `delivery_unconfirmed` must not be described as successful tracing. Local artifacts remain available independently of ordinary log rotation.

Include sanitized LangSmith screenshots only if an actual authorized screenshot exists. Otherwise include a clearly labeled conceptual trace tree and reproducible dashboard steps. Background trace export is observability, not LLM-as-judge automation or continuous quality evaluation.

## 19. Golden datasets and synthetic fixtures

Inventory the current master V1 CSV, four per-agent views, companion case details, manifest and README. Verify actual row counts; the current reference scope is 80 draft cases, 20 per agent, not 80 human-approved runs.

Preserve the six canonical fields: `scenario`, `user_input`, `expected_behavior`, `success_criteria`, `tools_context`, `failure_edge_cases`. Use canonical case IDs and meanings directly from CSVs; do not recycle illustrative IDs for different scenarios.

Explain fixture trip/provider/guide/specialist/currency records, fixed clocks, IDs, expected behavior, hashes and `evals/validate_fixtures.py`. Differentiate synthetic operational data, archived real guide excerpts and live provider evidence. A correctly handled synthetic outage can be a passing agent case. A fixture validator does not run agents or prove semantic retrieval quality.

**Keep fixtures, answers, labels and judge results outside destination Chroma.** Show their paths and how isolated test stores differ from local/Cloud destination collections. Do not manufacture missing failures, labels, real-user provenance or approval to satisfy sample quotas.

## 20. Evaluation lifecycle, human review and LLM-as-judge

Map the agreed lifecycle to actual and planned artifacts:

1. Plan goals, risks and policies.
2. Curate/review/version golden cases and select metrics before measurement.
3. Capture B0 against fixed task inputs, fixtures, model/prompt/code/corpus versions.
4. Monitor/classify errors with reproducible evidence.
5. Refine one factor at a time and re-evaluate.
6. Calibrate a judge against human-reviewed outputs and validate on an independent holdout.
7. Enable sampled continuous tracking only after its acceptance gates; feed findings into reviewed improvements.

Explain the user's intended sequence: implement/test agents → capture actual responses → independent human review/adjudication → freeze response/evidence/label versions → calibrate/validate the judge → reuse the same frozen responses to compare judge versions. Changed agent output requires new human review; a query's old response label cannot transfer automatically.

Inventory `agent_responses.csv`, `human_reviews.csv`, `adjudicated_labels.csv`, `judge_evaluations.csv`, `item_labels.csv`, `metric_summaries.csv`, their schema/manifest and any later runners. Describe row units, foreign keys, hashes, rubric versions, splits, statuses and privacy. Empty templates do not establish reviewed ground truth.

Separate exposed development cases, additional E2E integration cases, protected agent holdouts, judge calibration and judge-response holdouts. Group related scenarios/outputs to avoid leakage. State remaining coverage and sample requirements from the plan; do not imply the initial 80 cases provide every population.

Report judge failure detection with failure as the positive class: TP=human fail/judge fail, FP=human pass/judge fail, FN=human fail/judge pass, TN=human pass/judge pass. Define precision, recall and F1, including null denominators, abstentions/errors, coverage, critical misses, sample sizes and uncertainty. Keep task quality, judge reliability and ordinal itinerary utility separate; no undifferentiated project F1.

Explain planned evidence-group recall@5 versus literal passage recall. Interchangeable passages can support the same atomic need; benchmark queries need an achievable five-chunk witness set for that gate. Literal passage recall has ceiling `min(5, R)/R`; unsupported queries use abstention checks. Do not count duplicate chunks or unjudged passages as proven relevant. Explain corpus-gap and broad-query evaluation separately.

List targets as proposed/frozen/measured, never as achieved from source code alone. A background judge cannot retroactively guarantee correctness of a delivered answer.

## 21. Configuration and operational runbook

Document actual dependencies and pinned versions from `pyproject.toml`/`uv.lock`, Python requirements, installation and root-directory assumptions. Explain editable-import issues on macOS and the explicit source-path workaround. Do not introduce Docker, GPU or a separately launched Chroma service as requirements unless configured.

Use these current launch patterns after verifying the CLI:

```bash
uv sync
PYTHONPATH=src uv run python -m tripradar_agents.cli --fixture
# Live mode, after configuring credentials:
PYTHONPATH=src uv run python -m tripradar_agents.cli
```

Explain UI `http://127.0.0.1:8501`, API `http://127.0.0.1:8000`, `/docs`, `/health`, `/ready`, restart and Ctrl-C. One launcher starts UI/API; stdio MCP servers are launched automatically per call. Show separate-process commands only when supported and clarify that no HTTP MCP port exists in the stdio slice.

Document shared configuration with safe placeholders:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=your-api-key
LLM_BASE_URL=https://api.openai.com/v1
TRIPRADAR_AGENT_LANGSMITH_TRACING=true
TRIPRADAR_AGENT_LANGSMITH_PROJECT=tripradar-agents
LANGSMITH_API_KEY=your-langsmith-key
```

Explain role-specific override precedence, fallback model defaults when shared fields are absent, custom-endpoint pricing requirements, key aliases and restart requirements. The OpenAI key, Chroma credentials and LangSmith key have separate purposes. Do not conflate chat models, embeddings and vector storage.

Include a configuration table: setting, purpose, default/source, secret classification, override precedence, restart need and failure behavior. Inventory ingestion settings, Chroma backend/collection, database path, call/read/token/time limits, rates, cost cap and tracing settings. Verify exact runtime values; the larger design's ceilings and recovery allowances may differ from the slice.

Include ingestion setup/model download, sources list, root-only/all-city ingestion, stage commands, resume/force/dry-run, search, stats, validation, Cloud-copy steps and rollback/backup instructions from actual CLI help/runbooks. Do not execute collection, paid calls, migrations or live trace upload merely to write a command example.

## 22. API and UI reference

For each actual endpoint, show method/path, authentication, accepted fields, status codes, sanitized example request/response and behavior on retries. Cover session creation/read/delete, chat submission, request polling, health/readiness and asynchronous terminal results. Distinguish job status from domain response status.

Explain that `202` means admitted, not completed; `503` may mean incomplete configuration while `/health` succeeds; `422` indicates request validation, whereas a post-admission model `ValidationError` becomes a failed job. Show `401/403`, `404`, `409`, `413` and `429` only as implemented.

Document the actual Streamlit form, selected dates, adults/rooms, exact origin airport, interests/request text, mode banner, disabled submission, pending state, errors, per-day display, budget/limitations and source attribution. Do not claim a chat widget, reviewer interface or rich itinerary editor merely because these appear in a plan.

## 23. Troubleshooting and demonstration guide

Create a symptom → likely cause → safe diagnostic → corrective action → verification table, covering:

- API unreachable versus running but unready; stale process after `.env` updates.
- OpenAI configured under shared names while old provider/role overrides remain.
- Missing/zero rates, unknown custom-model pricing or missing provider credentials.
- Wrong/expired session or switching between fixture/live backends.
- Idempotent replay returning an old failed request instead of generating a new run.
- Model proposal numeric-type `ValidationError`, malformed JSON and schema/stage diagnostics.
- One fixture activity and empty remaining days; insufficient live evidence versus filtered claims.
- MCP timeout, unexpected catalog, subprocess/import failure or environment mismatch.
- Missing Chroma collection/model cache, local/Cloud mismatch and incompatible embeddings.
- Weather dates outside actual coverage; unknown prices and incomplete budget coverage.
- Exhausted model/read/token/deadline/cost reservations.
- LangSmith `delivery_unconfirmed`, wrong project/region/workspace or a stale backend.
- Local log path/rotation, port conflicts and macOS editable-package import behavior.

Provide a short reproducible fixture demonstration and a separate live demonstration checklist. Identify what each proves and does not prove. Use obviously synthetic trips and credentials; never fill missing activities/prices merely to improve the demonstration. Live API quota/authentication errors must not be relabeled as offline test failures or hidden by fixture fallback.

## 24. Validation report, roadmap and handoff

Report actual checks with command, environment/mode, date, result, skipped tests and evidence path. Separate fixture integrity validation, agent protocol/UI tests, mocked OpenAI/LangSmith adapter tests, local Chroma tests, live provider checks, retrieval relevance and human/judge evaluation. Do not infer live quality from a passing test suite.

If running checks is authorized, prefer offline tests and avoid telemetry/paid requests. Never report a new test run that was not performed. Do not use an old count from the reference project or earlier conversation as current evidence.

Prioritize remaining work with dependencies and acceptance evidence: useful multi-day retrieval/coverage; live provider adapters; normalized offers/FX and complete budget evidence; selected-offer reconciliation and affected rechecks; reliable observability delivery; reviewed claim/retrieval benchmarks; E2E/holdouts; human-reviewed B0; judge calibration/automation; then continuous tracking and production hardening. Flag limitations in current persistence, parsing, security and telemetry without claiming the whole design is complete.

End with a developer/operator handoff: where code and prompts live, where configuration is set, how to run/stop/test, where logs/evidence are stored, how to interpret partial results and where the next acceptance gates are defined.

## 25. Mandatory package/file responsibility catalog

Include a concise responsibility table for every maintained source module and meaningful configuration/test/evaluation file. Group by root/tooling, ingestion, agent runtime, prompts/security, evaluations, tests, operations docs and generated artifacts. Identify important symbols and their callers where helpful; do not substitute a folder tree for the file-level explanation.

Explicitly distinguish maintained code from `data/` artifacts, model/vector caches, SQLite, logs, generated documents, `.venv`, bytecode and build metadata. A generated artifact is not necessarily safe to delete: retained evidence, manifests, active pointers and databases need appropriate backup/retention handling. Never suggest deleting all runtime data as routine troubleshooting.

## 26. Final document acceptance checklist

Before delivery, confirm:

- The document covers both ingestion and runtime as one TripRadar application.
- It uses the current parent-root paths, actual modules and deployed transport/process boundaries.
- Shared OpenAI settings, model overrides and local MiniLM/Chroma roles are distinct and accurate.
- All four planning agents, tool-free verifier and future evaluation judge are correctly distinguished.
- Current behavior is separated from the larger target plan throughout text, tables and diagrams.
- Fixture-only activity/weather/pricing behavior is clearly labeled; no guaranteed itinerary completeness or budget fit is fabricated.
- Request validation, provenance, history/idempotency, transactions, failure/restart behavior and limits match code.
- Guardrail claims acknowledge semantic and prompt-injection limitations.
- Source attribution, snapshot identity, freshness and evidence traceability are explained.
- Golden IDs/counts and review-template status are verified, with no invented human labels or metrics.
- Precision/recall/F1 and retrieval units have valid populations/denominators and achievable thresholds.
- LangSmith enablement is distinguished from confirmed delivery and from judge automation.
- Logs, screenshots and examples contain no keys, session capabilities or private conversations.
- Test/corpus/live-service claims have dated evidence; missing verification is visible.
- All file links and figure references resolve; diagrams agree with the written architecture.
- DOCX/PDF figures and tables are readable, captions stay with figures, and conversion/layout checks are actually performed if those outputs are generated.
- Only requested documentation artifacts are changed; application code, `.env`, datasets and external systems remain untouched by documentation generation unless separately authorized.

Finish with links to the files actually produced and a brief statement of unverified claims, unavailable formats or missing evidence. Do not end with a blanket assertion that all planned features are complete.
