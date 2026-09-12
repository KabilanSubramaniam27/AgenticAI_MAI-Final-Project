# First agent vertical slice (historical milestone)

> The implementation has since expanded. See [current implementation status](implementation-status.md)
> for pricing/FX, reconciliation, recovery, EDD and tracking. The scope reductions below describe
> the original milestone and are not the current feature list.


This milestone implements Streamlit → FastAPI → DeepAgents orchestrator → three registered
specialists → four MCP domain servers → deterministic/semantic checks → persisted response.
It is a **provisional itinerary slice**, not full UC1 acceptance or a live booking-price demo.

Run from the repository root:

```bash
uv sync
PYTHONPATH=src uv run python -m tripradar_agents.cli --fixture
```

Open http://127.0.0.1:8501 (UI); http://127.0.0.1:8000/docs exposes API documentation.
Ctrl-C stops both services. Do not start a second API worker against the same database.
The launcher binds loopback only. Sessions use per-thread bearer capabilities; this is a local
single-user application, not public production authentication.

Fixture mode exercises the real DeepAgents graph, all four roles, real MCP handshakes/tool calls,
SQLite and UI, using a **scripted model**, archived guide passages and synthetic price/weather
responses. It proves plumbing and boundary behavior, not LLM quality. Synthetic amounts are
whole-party/stay examples; daily expenses remain unknown, so a subtotal never implies budget fit.
The fixture database/logs live under `data/runtime/fixture/`. No fixture writes to destination Chroma.

For live model/retrieval/weather execution, put these values in the ignored `.env`:

```dotenv
TRIPRADAR_AGENT_MODE=live
TRIPRADAR_AGENT_PROVIDER=openai
OPENAI_API_KEY=your-existing-openai-key
TRIPRADAR_AGENT_INPUT_USD_PER_MILLION=2
TRIPRADAR_AGENT_OUTPUT_USD_PER_MILLION=8
```

Use numeric rate values from your provider account; use upper rates covering both configured
models. Costs are conservative reservations, not measured invoices. The existing `CHROMA_*`
credentials are reused. Cloud is the default; set `TRIPRADAR_AGENT_CHROMA_BACKEND=local` to use
the published local index. Then run `PYTHONPATH=src uv run python -m tripradar_agents.cli`. Missing credentials/rates block model
execution and are listed by `/ready`; configuration readiness does not prove provider availability.
No model-availability probes or paid live agent calls have been included in offline acceptance.

Live destination retrieval uses existing MiniLM embeddings with Chroma semantic search.
Weather reads Open-Meteo and retains only actual requested dates returned by the forecast.
**Live flight/hotel pricing is not enabled in this milestone.** Its MCP server returns explicit
unavailable evidence. No flight/hotel selection is represented as reconciled. Activities are
provisional, unfilled days are visible, and the budget is unknown unless an evidenced lower bound
already exceeds it. This limitation also applies to fixture demonstrations; they do not establish
price-provider correctness or a complete ten-day activity plan.

System prompts are in `config/prompts/`, with shared instructions in `common_policy.md` and
one prompt per role. Deterministic enforcement resides in `src/tripradar_agents/security.py`,
`llm.py`, `api.py`, `store.py` and the MCP client/server boundaries. DeepAgents' default filesystem,
shell, planning and general-purpose delegation tools are removed from the model-visible catalog
and denied again before execution. Subagent descriptions cannot overwrite application trip state.
The extraction stage has no tools; only explicit `field: value` assignment messages can become trusted fields without a form, and
application validation resolves or asks for clarification. Prefer the structured form for this slice.
Ambiguous month/year prose needs clarification. Input filtering is conservative and can reject
benign quoted instructions; keyword detection is not complete prompt-injection protection.

Every LLM dispatch records redacted input/output, prompt hash, allowed tools and errors in
`data/runtime/logs/application.log`; agent/tool/RAG calls share request IDs. Only the API process
writes/rotates that file. Stdio MCP servers do not write it; their calls/results are traced at the API's
client boundary. Candidate outputs, evidence and model records are stored with the result in SQLite,
independently of log rotation. Raw framework auto-tracing remains disabled. An opt-in redacted LangSmith exporter sends
request, agent, LLM, MCP-tool and retrieval spans after request completion. No hidden reasoning is requested or logged.

A semantic verifier checks proposed claims before fixed rendering; IDs, destination, dates and exact
source quotes are checked deterministically. A verifier pass is fallible, not proof of truth. The
fixture verifier tests exact-copy support only. Human claim labels and live-model evaluation are
still needed. No background evaluation judge is implemented or used as a runtime safety gate.

## Selected scope reductions from the full plan

- Stdio MCP servers are started per call with application-owned immutable context and closed after
  use. Streamable HTTP, shared long-running servers and collector endpoints are deferred.
- Agents have their respective essential MCP capabilities; optional cross-agent RAG is deferred.
- One modest activity/day is requested; no automatic offer/weather revisions or recovery loops.
  Global caps still apply; failures stop rather than silently retry/fallback.
- Conservative byte-based token upper bounds and 1,500 output tokens per call are used. Up to
  12 model attempts/20 reads/120 seconds; no claim that every complex trip fits these caps.
- Live pricing/FX normalization, accepted spending allowances, complete budget coverage, flight/hotel
  reconciliation, provider readiness probes and calibrated semantic-verifier acceptance remain open.
- SQLite stores admitted user input and terminal answer on one request row, giving atomic history
  without duplicate message-table writes. Queued/running jobs become interrupted on restart;
  no paid work is automatically replayed. Last ten completed exchanges are loaded for context.
- Request records/evidence are purged after 90 days at startup. Sessions expire after 30 days inactive
  or 90 days total. New trip deletes its session/history/evidence. Benchmark freeze/export and periodic
  retention maintenance are deferred. Logs rotate at 10 MB with five backups; age-based expiry is deferred.
- Judge automation, E2E golden holdouts, B0 live outputs/human reviews, continuous tracking remain subsequent milestones. Existing golden datasets are unchanged.

## Validation

```bash
PYTHONPATH=src uv run pytest tests/agents -q
```

Tests cover the actual fixture graph/MCP path, pre-model input rejection, session isolation,
idempotency, queued/running restart interruption, late-result rejection, provenance, forged budget
IDs, unknown cost coverage, forbidden default tools, and Streamlit form/poll/render behavior.
The Streamlit test uses an HTTP contract double; the API integration test uses real MCP subprocesses.
These tests are not a pass report for the 80 golden agent cases.

Sources used for SDK integration: [DeepAgents customization](https://docs.langchain.com/oss/python/deepagents/customization),
[registered subagents](https://docs.langchain.com/oss/python/deepagents/subagents),
[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).

## LangSmith observability

Enable agent tracing in your ignored `.env` and restart the API:

```dotenv
TRIPRADAR_AGENT_LANGSMITH_TRACING=true
TRIPRADAR_AGENT_LANGSMITH_PROJECT=tripradar-agents
LANGSMITH_API_KEY=your-langsmith-key
```

Existing `LANGSMITH_API_KEY`, `LANGSMITH_ENDPOINT` and `LANGSMITH_WORKSPACE_ID` are reused.
Optional `TRIPRADAR_AGENT_LANGSMITH_*` credential/endpoint overrides take precedence. The agent
flag/project are independent of ingestion's settings. Do not enable raw framework auto-tracing:
manual sanitized RunTree exports work even while that mechanism remains disabled.

Submit a request, then open the `tripradar-agents` project in LangSmith. Fixture runs are tagged
`fixture`, never presented as live LLM evaluations. Request/thread IDs link nested agent, model,
MCP-tool and retrieval spans with `application.log`; model spans include permitted redacted
inputs/outputs and tool catalogs. Source evidence appears in model inputs/final output, while
retriever spans summarize query/evidence IDs. Prompts and user/history content are transmitted
in redacted form when you opt in; heuristic secret redaction is not general PII anonymization.

`GET /ready` reports the exporter status. A `langsmith.exported` local event contains a trace URL
only after root readback; child visibility can lag. Missing keys, upload failures, queue saturation
or incomplete shutdown draining report degraded/unconfirmed delivery. Local evidence and planning
continue. The queue is bounded (32 requests), upload runs on a dedicated worker and shutdown waits
up to five seconds. This is best-effort post-request tracing, not a durable telemetry outbox; a hard
crash may lose pending uploads. Judge automation and continuous quality scoring are still deferred.

Offline tests cover actual RunTree serialization/hierarchy with a fake SDK client, redaction,
disabled/missing-key behavior and delivery failure. They do not establish delivery to your account.
See [LangSmith custom instrumentation](https://docs.langchain.com/langsmith/annotate-code).

## OpenAI provider configuration

OpenAI is now the default provider. The existing `OPENAI_API_KEY` is read directly; optional
`TRIPRADAR_AGENT_OPENAI_API_KEY` takes precedence. Orchestrator and runtime verifier default to
`gpt-4.1`; specialists default to `gpt-4.1-mini`. Both remain configurable through
`TRIPRADAR_AGENT_MODEL` and `TRIPRADAR_AGENT_SPECIALIST_MODEL`. Restart the backend after changes.
`/ready` reports the selected provider/models without credentials. Account access is not established
by local readiness alone. Only `openai` is accepted as the provider; no alternative-provider fallback is configured.

For the default pair, conservative shared reservations use $2 input / $8 output per million tokens,
covering standard text pricing for both models. These are rate-card estimates, not invoices;
explicit rates override defaults and unrecognized model IDs require explicit rates. See the
[GPT-4.1 model page](https://developers.openai.com/api/docs/models/gpt-4.1) and
[GPT-4.1 mini model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
Offline tests exercise the actual OpenAI adapter/DeepAgents graph against a mocked API response;
no paid completion or account/model-access claim is made by these tests.

### Model API compatibility

All agent roles (including extraction and grounding verification) use the same model boundary.
OpenAI calls use JSON mode; when delegation tools are present, binding enables strict function
schemas and disables parallel tool calls. Calls without tools do not receive tool-binding settings.

Offline SDK tests cover JSON results for every role on OpenAI and three consecutive
specialist delegations followed by a final response. Existing integration tests cover FastAPI,
MCP, Chroma and tracing separately; those protocols do not take OpenAI function-tool settings.
Custom OpenAI base URLs must implement the same JSON-mode and strict-tool contract; arbitrary
third-party endpoints and models are not certified by these tests. Restart the backend after
updating code and submit a new request; an idempotent replay retains the original failed result.

## Shared LLM environment variables

The user's shared configuration is supported directly:

```dotenv
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=your-replacement-key
LLM_BASE_URL=https://api.openai.com/v1
```

`LLM_MODEL` applies to all four agents and the runtime verifier. Explicit
`TRIPRADAR_AGENT_PROVIDER`, `TRIPRADAR_AGENT_MODEL`, `TRIPRADAR_AGENT_SPECIALIST_MODEL`
and `TRIPRADAR_AGENT_BASE_URL` override the corresponding shared settings. Remove older
role overrides if you want every role to use the shared model. With no shared model or overrides,
the earlier GPT-4.1/GPT-4.1-mini defaults still apply. The base URL is passed to the OpenAI client.

For GPT-4o mini on the standard OpenAI endpoint, automatic reservation rates are $0.15 input and
$0.60 output per million tokens unless explicitly overridden; mixed models use the maximum rate.
Custom endpoints require explicit rates. These are configuration estimates, not account billing
verification. [Official model pricing](https://developers.openai.com/api/docs/models/gpt-4o-mini).
Restart the backend after changing `.env`. Tests use synthetic credentials and mocked responses;
no live request is made with the key exposed in the conversation.
