# TripRadar destination ingestion

To copy the existing local index into Chroma Cloud, see [Cloud upload setup](docs/chroma-cloud.md).

Collect source-attributed English Wikivoyage guides for **Lisbon, Paris, London, and New York City**, including bounded district/borough guides. Preserve revision-pinned wikitext, extract listings and sections, normalize and chunk them, generate local MiniLM embeddings through Chroma, and publish a validated persistent Chroma index. LangSmith traces and local JSONL events show stage timings, counts, failures, cache reuse, and publication.

This package implements the knowledge ingestion/retrieval layer. Agents, itinerary generation, live hotel/flight pricing, forecasts, and budget reconciliation remain future work. Portugal coverage is Lisbon and collected districts; guide prices are not live offers.

## Setup

Python 3.12 is recommended. Install [uv](https://docs.astral.sh/uv/) if needed, then run from the project root:

```bash
uv sync --locked --no-editable
source .venv/bin/activate
tripradar-ingest sources list
tripradar-ingest setup-model
tripradar-ingest health --check-embeddings
```

`uv.lock` pins the tested dependency set. `--no-editable` installs a regular package, avoiding macOS hidden-file flags on editable import hooks. After changing source code, rerun installation before using the installed CLI, or use `PYTHONPATH=src` during development. Chroma's local `all-MiniLM-L6-v2` produces **384-dimensional** vectors. `setup-model` downloads approximately 80 MB of model assets into `data/models/`, checks the vendor archive checksum, records file checksums, and verifies inference. Once cached, embedding and local search need no network or provider key. No Docker or database service is required.

If the OS marks editable `.pth` files hidden and the console entry point cannot find the package, use `PYTHONPATH=src .venv/bin/python -m tripradar_ingestion.cli ...` from the root. macOS Python skips hidden `.pth` files; reinstalling alone may not clear that filesystem flag.

Configuration is in `config/settings.yaml` and `config/destinations.yaml`. `.env.example` documents optional overrides. If `.env` already exists, merge only the settings you want; do not replace its credentials. Ingestion uses **`TRIPRADAR_`-prefixed variables** to avoid picking up old provider/embedding settings. LangSmith uses the conventional `LANGSMITH_*` variables, with optional `TRIPRADAR_LANGSMITH_*` overrides. This workspace has `TRIPRADAR_LANGSMITH_PROJECT=tripradar-ingestion` so its existing shared project setting is preserved. Configure an identifying User-Agent with your project URL or contact before repeated collection:

```dotenv
TRIPRADAR_SCRAPER_USER_AGENT=TripRadarIngestion/0.1 (+https://your-project.example/contact)
LANGSMITH_TRACING=false
```

Do not use the illustrative URL literally. Existing `.env` secrets are not copied into artifacts. Set `TRIPRADAR_ROOT` when calling the installed package outside the checkout. All data paths resolve relative to this root.

## Run ingestion

```bash
# Small first run, one city root article
tripradar-ingest ingest --destination lisbon --root-only

# All four cities and bounded districts
tripradar-ingest ingest --all

# Inspect scope without network, downloads, tracing, or writes
tripradar-ingest ingest --all --dry-run

# Resume the last logical run with the same scope/options
tripradar-ingest ingest --all --resume

# Recheck/reprocess one destination, preserving other active cities
tripradar-ingest ingest --destination lisbon --force
```

The API is public and requires no key. Requests are sequential, respect configured spacing and `Retry-After`, and retry transient failures. API errors inside HTTP 200 are handled as errors. District discovery uses explicit `Regionlist`/district hierarchy fields, including Paris's `regionNitems`; it never follows arbitrary external websites or every matching title prefix. Defaults: depth two and at most 40 district pages per city. Coverage reports list cap/depth exclusions. Configure extra district titles explicitly when hierarchy templates do not enumerate them.

Every run prints stage progress to stderr and a JSON summary to stdout. A source failure preserves successful raw downloads, continues independent cities, returns a nonzero exit status, and prevents publication of an incomplete replacement snapshot. `--resume` reuses completed stages in the same logical run; successful raw revisions and embedding caches also survive later runs. `--force` recomputes processing but can reuse identical embedding inputs.

## Run separate stages

```bash
tripradar-ingest collect --all
tripradar-ingest parse --all
tripradar-ingest normalize --all
tripradar-ingest chunk --all
tripradar-ingest embed --all
tripradar-ingest index --all
tripradar-ingest validate
tripradar-ingest stats
tripradar-ingest sources stale --days 30
```

`normalize` includes cleaning and exact block deduplication. Empty sections are reported; useful short warnings are retained. Known listing fields survive markup removal. Unknown template names/raw text are retained in parsed diagnostics, and visible parameter values are preserved for review. No LLM performs cleaning or enrichment. Activity environment defaults to `unknown` rather than guessing indoor/outdoor suitability.

Chunks target 180 model tokens, with up to 24 tokens of overlap inside split prose and a 256-token ceiling including context/special tokens. Exact text offsets and source-revision metadata remain attached. A separate, nontruncating copy of the model's tokenizer validates inputs before the Chroma embedding function runs.

## Search and validate

```bash
tripradar-ingest search "public transport from the airport" --destination lisbon --section get_in --top-k 5
tripradar-ingest search "art museums" --destination Paris --section see
tripradar-ingest search "budget accommodation" --destination NYC --section sleep
tripradar-ingest validate
```

Results include exact guide text, destination, section, stable chunk/document IDs, original/revision/history URLs, revision/fetch dates, and attribution. Cosine distance is lower-is-better; `score = 1 - distance` is similarity, not confidence. Destination and section filters run inside Chroma. Unknown destinations fail explicitly; missing sections return `not_covered`. No arbitrary relevance cutoff is presented as calibrated confidence.

The Python entry point for later agent/MCP integration is:

```python
from tripradar_ingestion.retrieval import search_guide
passages = search_guide("Lisbon", section="see", query="museums", k=5)
```

Every collection generation is built separately, read back, and checked before switching `data/manifests/active_collection.json`. Archived normalized sections and checksum-verified raw files remain linked from every chunk. Failed validation preserves the old pointer. Changes remove obsolete chunks through replacement snapshots; other cities survive targeted updates. Retain previous collections for rollback; no automatic pruning/reset command runs. Back up the Chroma directory, manifests/active pointer, snapshot files, and embedding cache together while writers are stopped.

## Observability

```dotenv
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your-key
LANGSMITH_PROJECT=tripradar-ingestion
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
# Set LANGSMITH_WORKSPACE_ID if your key requires it.
```

Use the endpoint matching your LangSmith region. Run ingestion, then open the `tripradar-ingestion` project and expand the trace: collection → parse → normalize/clean/deduplicate → chunk → local embedding batches → Chroma upsert/validate/publish. Inputs/outputs are hidden; only stage summaries and source IDs/metadata are exported. No full guide text, vectors, or credentials are traced. A trace URL is reported only after readback confirms delivery.

Local events always remain at `data/reports/<run_id>/events.jsonl`; the final summary is `data/reports/<run_id>.json`. Resume shares a logical run ID but has a new attempt and trace. Export failure leaves ingestion operational and reports telemetry as unconfirmed/unavailable. See [observability operations](docs/ingestion-observability.md).

## Tests and quality

```bash
.venv/bin/pytest
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
tripradar-ingest evaluate
```

Unit tests use synthetic API/embedding fixtures, do not download models, and do not export traces. Local Chroma integration tests run in temporary databases. The cached real-model test skips until `setup-model` has completed. Live external tests, if selected, are explicitly marked `live` and excluded by default. Retrieval evaluation uses documented supporting passage phrases rather than generated answers; see [validation results](docs/validation.md) for actual checks and limitations.

## Layout

```text
config/                         city registry and nonsecret defaults
src/tripradar_ingestion/         CLI, collection, parsing, normalization, chunks,
                                local embeddings, Chroma, retrieval, checkpoints, traces
data/raw/wikivoyage/             original API responses and wikitext by page/revision
data/parsed/, normalized/      section/listing records and diagnostics
data/chunks/, embeddings/      exact chunks and reusable local vectors
data/chroma_db/                persistent Chroma database
data/manifests/, reports/      checkpoints, active snapshot, coverage, run events
prompts/DataIngestion.md         reviewed design and implementation notes
Trip-Planner-prompts/            future application/agent reference documents
tests/                          processing, collection, persistence and pipeline tests
```

Generated data/model caches are gitignored. No code was copied from the earlier project. Text attribution and licensing are described in [source attribution](docs/source-attribution.md).

## TripRadar agent vertical slice

Run the complete local fixture flow (Streamlit → FastAPI → DeepAgents → specialists/MCP):

```bash
uv sync
PYTHONPATH=src uv run python -m tripradar_agents.cli --fixture
```

Open http://127.0.0.1:8501. Fixture mode is explicitly labeled and uses no paid LLM calls.
Live model/Chroma/weather configuration, guardrails, tests and remaining milestones are documented
in [the agent slice guide](docs/agents/vertical-slice.md). Live flight/hotel pricing is not enabled yet;
results are provisional, with unknown costs/coverage shown explicitly. Judge automation is deferred.

Agent LangSmith observability is available: set `TRIPRADAR_AGENT_LANGSMITH_TRACING=true`
and provide `LANGSMITH_API_KEY` in `.env`, then restart. Redacted traces go to `tripradar-agents`;
ingestion tracing remains separate. See [LangSmith setup](docs/agents/vertical-slice.md#langsmith-observability).

## Expanded agent implementation

See [implementation status and runbook](docs/agents/implementation-status.md) for the four OpenAI
agents, runtime verification/repair, Amadeus/FX adapters, evidence-bound budget, and EDD workflow.
Human acceptance and live-provider verification remain separate gates. Start the UI/API with:

```bash
PYTHONPATH=src .venv/bin/python -m tripradar_agents.cli
```

Evaluation commands are available via `python -m tripradar_agents.evaluation --help` with
`PYTHONPATH=src`. Synthetic fixtures and captured benchmarks remain separate from destination Chroma.
