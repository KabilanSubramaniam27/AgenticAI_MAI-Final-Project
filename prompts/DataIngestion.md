# TripRadar destination data ingestion plan

Status: implementation authorized. The package now lives under the parent project root; see README.md for executable commands and docs/validation.md for measured verification results. The sections below retain the approved design, with operational differences listed at the end.

## 1. Objective and scope

Build a standalone Python ingestion package under the parent project's `src/tripradar_ingestion/` directory that collects English Wikivoyage destination content, preserves the original responses, parses and cleans the content, normalizes destination metadata, creates source-traceable chunks, embeds them locally through Chroma’s default embedding function, and persists them in Chroma DB for semantic retrieval.

The initial destinations are **Lisbon, Paris, London, and New York City**. Configuration must allow more destinations without changes to collector logic.

This prepares the knowledge layer for Itinerary-Builder and, later, Trip-Planner's reconciliation workflow. Flight/hotel offers, dated weather results, currency conversion, agents, MCP servers, UI, and itinerary generation are subsequent work. Guide prices are historical guidance, never live quotes. Guide climate descriptions are not forecasts.

For UC1, the initial Portugal coverage is Lisbon and its included districts. It does not establish nationwide coverage or support an arbitrary Portugal route. The future planner must disclose this scope or request a supported city. It must also resolve travel year, exact dates, origin airport, traveler count, budget inclusions, and day/night conventions before pricing; ingestion does not need these inputs.

## 2. Existing references and design decisions

Use the earlier `AgenticAI_Wk4_Project` directory layout and `prompts/DataIngestion.md` as organizational references: configuration, a `src` package, separate data stages, manifests, CLI commands, tests, and operational documentation. Implement all code independently; do not copy its collectors, schemas, or provider integration code.

Use Chroma for both local embedding generation and persistent vector storage. Explicitly select its `DefaultEmbeddingFunction`, backed by `all-MiniLM-L6-v2`, and retain the source-grounded retrieval contract in [AGENTS.md](../Trip-Planner-prompts/AGENTS.md). This aligns with the local model and database choices in [IMPLEMENTATION.md](../Trip-Planner-prompts/IMPLEMENTATION.md); package locations and detailed ingestion behavior follow this plan.

| Component | Proposed choice |
| --- | --- |
| Runtime | Python 3.12+; initial implementation verified with Python 3.12 |
| HTTP collection | `httpx`, with bounded retries and explicit API error handling |
| Wikitext parsing | `mwparserfromhell`; template-specific extraction before markup removal |
| Validation/configuration | Pydantic, pydantic-settings, YAML |
| CLI | Typer and Rich |
| Embeddings | Chroma `DefaultEmbeddingFunction`, local `all-MiniLM-L6-v2`, exactly 384 dimensions |
| Vector database | Persistent local Chroma via `chromadb`; logical collection `tripradar_destinations` |
| Token counting | Exact tokenizer from the selected Chroma model assets, with explicit input-length validation |
| Local database deployment | Embedded Python client with project-owned disk persistence |
| Checkpoints | SQLite manifest plus JSON run reports |
| Observability | LangSmith SDK for stage traces; structured local logs and durable run reports |
| Tests/checks | pytest, respx, Ruff, and type checks |

Wikivoyage collection and local embedding/vector storage need no API key. Chroma’s default embedding function downloads model files on first use, then runs locally using the cached assets. Make that download an explicit setup step. Pin `chromadb` and compatible local inference dependencies, and record model/tokenizer artifact checksums. Local Chroma requires a writable persistence directory. LangSmith remains optional and requires its own credentials when enabled.

## 3. Project structure

This plan lives at `prompts/DataIngestion.md` in the parent project root (`AgenticAI_MAI-Final-Project` in the current workspace). All Python packages are implemented under this root's `src/` directory, with configuration, data, tests, and project tooling alongside it. The existing `Trip-Planner-prompts/` folder contains reference documents only; do not place implementation packages beneath it. All relative implementation paths and command examples in this plan are rooted at the parent project directory.

```text
AgenticAI_MAI-Final-Project/
  prompts/
    DataIngestion.md
  Trip-Planner-prompts/                 # existing reference documents
    AGENTS.md
    IMPLEMENTATION.md
    TRIPRADAR.md
  README.md
  pyproject.toml
  .env.example
  .gitignore
  config/
    destinations.yaml
    settings.yaml
  src/
    tripradar_ingestion/
      __init__.py
      cli.py
      config.py
      models.py
      registry.py
      collector.py
      parser.py
      normalizer.py
      cleaner.py
      chunker.py
      embeddings.py
      vectorstore.py
      retrieval.py
      manifest.py
      pipeline.py
      reporting.py
      observability.py
  data/
    raw/wikivoyage/
    parsed/
    normalized/
    chunks/
    embeddings/
    manifests/
    reports/
    chroma_db/                   # project-owned database persistence
  docs/
    ingestion-operations.md
    ingestion-observability.md
    source-attribution.md
  tests/
    fixtures/wikivoyage/
    unit/
    integration/
    retrieval/
```

Ignore downloaded data, model/tokenizer caches, vector storage, logs, and `.env` in version control. Commit only small attributed test fixtures. Future agents and MCP packages will also live under the parent project's `src/` directory, separately from `tripradar_ingestion`; do not create placeholder implementations for them now.

## 4. Source registry and bounded coverage

| Destination ID | Display name | Requested Wikivoyage title | Country | Aliases |
| --- | --- | --- | --- | --- |
| `lisbon` | Lisbon | `Lisbon` | PT | Lisbon |
| `paris` | Paris | `Paris` | FR | Paris |
| `london` | London | `London` | GB | London |
| `new_york_city` | New York City | `New York City` | US | New York, New york, NYC |

Use `https://en.wikivoyage.org/w/api.php` as the API endpoint and restrict fetched destination pages to English Wikivoyage's article namespace. Resolve redirects and persist both requested and canonical titles. New York means the city in this configured MVP, not New York State; the canonical article is [New York City](https://en.wikivoyage.org/wiki/New_York_City).

Each registry entry contains destination ID, title, aliases, country, enabled status, optional explicitly configured district titles, and discovery bounds. Country metadata is configuration, not extracted evidence about an attraction.

Four cities do not necessarily mean four articles. Collect all four root articles first, then include district/borough articles identified by destination hierarchy links or configured explicitly. Proposed limits: maximum two hierarchy levels and 40 additional pages per city. Follow only pages within the configured destination hierarchy, deduplicate by resolved page ID, and never follow arbitrary attraction websites, country links, or “Go next” destinations. Ordinary prefix matches alone are insufficient to establish a district relationship. Resolve discovery ambiguity in the registry during implementation and record excluded candidates and cap hits in the coverage report.

Support `--root-only` for a minimal collection run. District expansion remains inside the four-city scope. The [New York City guide](https://en.wikivoyage.org/wiki/New_York_City) illustrates why borough coverage matters. Do not claim complete attraction coverage merely because a root page was downloaded.

## 5. Acquisition and raw preservation

Use the official API rather than browser scraping. The user's Lisbon URL is the starting pattern:

```text
https://en.wikivoyage.org/w/api.php?action=parse&page=Lisbon&format=json&prop=wikitext
```

Proposed collection sequence:

1. Resolve configured titles through `action=query`, with redirects enabled; request page identity, canonical URL, and revision ID/timestamp using `prop=info|revisions` and `rvprop=ids|timestamp`.
2. Retrieve wikitext with `action=parse&oldid=<resolved_revision_id>&prop=wikitext|revid&format=json&formatversion=2`. Pinning `oldid` keeps content and revision metadata consistent.
3. Validate HTTP status, JSON shape, API-level errors, nonempty content, and matching revision identity.
4. Save the unmodified API response, extracted wikitext, and retrieval metadata before transformation.
5. Discover bounded district candidates from the preserved page; resolve and collect eligible pages through the same path. Handle continuation wherever an API query uses pagination.

MediaWiki documents revision lookup in [API:Revisions](https://www.mediawiki.org/wiki/API:Revisions), and revision-pinned parsing and wikitext retrieval in [API:Parsing wikitext](https://www.mediawiki.org/wiki/API:Parsing_wikitext). Use local heading parsing rather than depending on the deprecated `prop=sections` API property. Verify actual response fixtures when implementation begins.

Raw artifacts use destination/page-ID/revision-ID paths; repeated identical downloads do not create new content copies. Save fetch events separately with UTC retrieval time, request parameters, status, content type, response hash, canonical URL, revision timestamp, and ETag/Last-Modified when supplied. A fresh fetch does not mean the underlying guide facts were freshly verified.

Use an identifying User-Agent with a real configurable contact or project URL, following the [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy). Start conservatively with one in-flight request and at least one second between calls. Set a 30-second timeout, four bounded retries with exponential backoff/jitter, and honor `Retry-After`. Retry timeouts, 429, transient 5xx responses, and API `maxlag` errors; do not loop on missing pages, invalid parameters, or access denial. API errors can arrive inside HTTP 200 responses.

There is no automatic HTML/browser fallback in the MVP. Persist failures, continue independent cities, and report a partial run with a nonzero exit status. Never manufacture source content to finish a run.

## 6. Parsing, cleaning, and normalization

Parse headings into a hierarchy, preserving lead text and the original section labels. Extract each section's direct content once so nested sections are not duplicated in their parent.

Controlled section keys: `overview`, `understand`, `get_in`, `get_around`, `see`, `do`, `buy`, `eat`, `drink`, `sleep`, `stay_safe`, `stay_healthy`, `connect`, `cope`, `go_next`, and `other`. Preserve the complete original section path alongside these keys. Do not discard useful prose solely because its heading is unfamiliar.

Process Wikivoyage listing templates such as `see`, `do`, `eat`, `drink`, `sleep`, and `listing` before removing templates. Retain available name, description/content, address, directions, URL, coordinates, hours, price text, phone, and source update annotations. Render these fields into readable labeled text and also save structured listing records. Blindly stripping templates would lose the very recommendations needed for RAG.

Cleaning rules:

- Decode entities, normalize Unicode and whitespace, and retain accents, currencies, units, negation, and seasonal qualifications.
- Convert internal links to visible labels while preserving useful link targets as metadata; preserve external URLs without fetching them.
- Remove comments, image markup, maintenance banners, navigation templates, and layout-only syntax.
- Handle known content-bearing templates explicitly. Log unknown templates and retain their raw reference for inspection; report potentially lost content instead of silently treating all unknown templates as junk.
- Preserve concise factual warnings and listings. Quarantine empty or malformed outputs with a reason.
- Do not use an LLM to rewrite, summarize, deduplicate, infer missing values, or classify an activity as indoor without source support.

Normalize destination aliases through the registry. District records carry the parent destination ID and their own page title/district field. Missing values remain null in JSONL. Guide price strings remain `guide_price_text`; parse numeric amounts only when currency and units are explicit, and never relabel them as current offers. An activity environment tag may be `indoor`, `outdoor`, `mixed`, or `unknown`, with the supporting text span and extraction rule recorded; default to `unknown`.

## 7. Data contracts and attribution

Use validated models with schema and processing versions:

| Artifact | Required information |
| --- | --- |
| Source page | Source ID/name, requested/canonical title, page ID, destination ID, country, language, revision ID/time, fetched time, canonical URL, revision permalink, history URL, license, raw hash/path |
| Normalized section | Document ID, page reference, section key, full section path, section occurrence, cleaned text, listing references, normalized hash, parser/cleaner versions |
| Listing | Listing ID, parent section, extracted fields, original template location, evidence text, nullable environment tag/support |
| Chunk | Chunk ID, document ID, destination, section/path, exact text, chunk order, normalized offsets or listing fragment reference, token count, content hash, provenance, chunker version |
| Embedding record | Chunk ID, input hash, embedding-function/model identity, model/tokenizer checksums, formatting-policy version, dimension, normalization setting, local token count, inference duration, timestamp, cache reference |

Every retrieved result must resolve to a saved chunk, normalized section, and raw page revision. Use actual page/revision IDs returned by the API; examples must never masquerade as collected records. A revision permalink is the minimum precise web citation. Add a section fragment only when reliably derived/validated; do not invent anchors for repeated headings.

Persist attribution as “Wikivoyage contributors,” article/history links, license identifier and URL, and a note that markup was cleaned and text chunked. The current [Wikivoyage copyleft policy](https://en.wikivoyage.org/wiki/Wikivoyage:Copyleft) specifies CC BY-SA 4.0 for text and attribution/share-alike requirements. Carry attribution through exported text datasets and retrieval results. Images are outside this ingestion scope.

## 8. Deduplication and deterministic identity

Use SHA-256 over canonical serialized fields, excluding retrieval timestamps:

- Page identity: source/language/page ID; redirects to the same page share identity.
- Document identity: page identity plus section path and occurrence.
- Chunk identity: document identity, chunker version, chunk ordinal, and content hash.
- Embedding cache key: exact input hash plus local embedding-function/model identity, model/tokenizer checksums, formatting-policy version, dimension, normalization, and embedding-space version.

Deduplicate exact repeated blocks within the same page/section context. Flag similar content across pages for review; do not automatically merge different attractions or remove district provenance. Identical text can share an embedding cache entry while keeping separate source records. A revision-only change can update provenance without recomputing unchanged vectors.

## 9. Chunking strategy

Use sections as the primary boundary, then paragraphs, sentences, and listing boundaries. Never mix cities or unrelated sections. Do not embed an entire long section as one vector.

Use the tokenizer shipped with the selected Chroma embedding model. The [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) describes 384-dimensional output and a default 256-word-piece input limit. Chroma’s packaged runtime may expose a different maximum; validate the actual runtime/tokenizer and apply the smaller of its supported limit and the conservative 256-token application ceiling.

Proposed defaults: target 180 model tokens of content, up to 24 tokens of overlap for split prose, and a hard ceiling of 256 tokens per complete embedding input, including any destination/heading prefix and special tokens. Count with the exact cached tokenizer used by the embedding function, with truncation disabled during validation. Reserve prefix space before splitting. Assert that neither document nor query inputs are silently truncated; split documents and reject oversized queries with a clear message.

Keep short complete listings intact. Split an oversized listing into labeled fragments retaining its name and parent ID. Apply overlap only inside the same section/listing. A short factual warning is valid even if below the ordinary target; boilerplate should be excluded by content rules rather than an arbitrary minimum alone.

Store citation text separately from the exact embedding input, whose small context prefix may include destination and section. Record token count and offsets against normalized text so citation reconstruction is testable.

## 10. Embedding and vector persistence

### Chroma local embedding function

Use Chroma's `DefaultEmbeddingFunction` explicitly, backed by `all-MiniLM-L6-v2`. The [Chroma embedding-function documentation](https://docs.trychroma.com/docs/embeddings/embedding-functions) describes local generation, direct invocation, and automatic embedding when adding or querying collection text. The model runs on the developer's machine; no hosted embedding account, API key, or per-request embedding fee is required. Local CPU, memory, disk, and initial download time still apply.

Keep the separate `embed` stage for observability and resumability: `embeddings.py` calls Chroma's embedding function directly on uncached batches, validates results, and saves them for `index`. This uses Chroma for embedding generation as well as storage. It does not introduce a separate model provider. Start with a configurable batch size of 32 and CPU execution; verify inference dependencies on the developer's machine.

Documents use cleaned text with a small destination/section prefix; queries use plain retrieval text. Version this formatting policy and count the exact model input. Do not add instruction prefixes intended for other models. Validate one vector per input, order alignment, 384 dimensions, finite values, and nonzero norm. Retain the embedding function's normalization consistently for documents and queries; verify its behavior and record it in the fingerprint.

Cache vectors under `data/embeddings/` using exact input hashes plus embedding-function identity, model/tokenizer artifact checksums, formatting policy, and settings. Persist completed batches so interrupted indexing does not repeat inference. Keep optional readable vector dumps disabled (`SAVE_EMBEDDINGS_DEBUG=false`). Report local input-token counts, inference time, and cache hits rather than provider usage or billed tokens. Fail clearly on missing/corrupt model assets, incompatible runtime, or invalid vectors; do not repeatedly retry deterministic errors.

### Chroma storage adapter

Use the `chromadb` Python package through a small independently written adapter, with `PersistentClient(path=CHROMA_PERSIST_DIRECTORY)`. Store the database at the parent project's `data/chroma_db/`. Chroma's [client documentation](https://docs.trychroma.com/docs/run-chroma/clients) describes automatic persistence and loading from disk.

Create and reopen collections with the explicitly selected Chroma embedding function. Chroma can automatically embed `documents` and `query_texts`; however, the ingestion pipeline supplies cached vectors on upsert so embedding and indexing remain separately traceable and inference is not repeated. The retrieval adapter calls the same embedding function and passes `query_embeddings` to expose query-embedding timing. Both paths must share the exact model and settings. Chroma stores supplied [embeddings alongside documents](https://docs.trychroma.com/docs/collections/add-data) without re-embedding.

Configure cosine distance explicitly at collection creation using the pinned client's supported configuration API. Chroma's [collection configuration guide](https://docs.trychroma.com/docs/collections/configure) documents the metric options. The first inserted embedding establishes collection dimensionality; validate every vector as exactly 384 dimensions before insertion, record the expected dimension in the collection fingerprint, and verify compatibility on reopen. Never rely on a default model or dimension.

Use the full deterministic SHA-256 chunk ID directly as Chroma's string record ID. Upsert matching `ids`, `embeddings`, `documents`, and `metadatas` batches; keep all arrays aligned and respect the pinned client's batch-size limits. Store citation text in `documents`, with destination/section, page/revision IDs, timestamps, source URLs, attribution, hashes, and chunk/document IDs in metadata. Flatten nested fields and omit null metadata values; retain complete records in JSONL.

Apply destination and optional section filters using Chroma's `where` conditions before selecting top-k, with `$and` when combining conditions. Verify filtering and readback against the pinned version; see [metadata filtering](https://docs.trychroma.com/docs/querying-collections/metadata-filtering). Paginate record validation instead of assuming a single read returns the complete collection.

Treat embedding-function/model identity, model/tokenizer checksums, embedding-space version, formatting policy, dimension, metric, normalization, and chunker settings as the collection fingerprint. Fail clearly on incompatible settings; do not mix embedding spaces or clear the database automatically. Changing the model or its assets requires a new validated collection generation and compatible query embeddings.

For this small corpus, publish via a staging collection: build the complete candidate snapshot, reusing cached embeddings, validate counts/IDs/documents/metadata and test queries, then atomically switch an application-managed local active-collection pointer. The logical name is `tripradar_destinations`; physical names include a generation ID. This does not assume Chroma supports transactional collection aliases. All retrieval consumers must resolve the pointer at request start. Failed rebuilds leave the previous active snapshot available. Keep the prior generation for rollback and make pruning explicit. A destination-specific refresh must retain the other destinations in the candidate snapshot.

### Local database operation

Run Chroma embedded in the Python application for this MVP. No Docker Compose, database server, network port, or database API key is required. Resolve the configured persistence path relative to the parent project root so commands run from different working directories reopen the same database.

Use project-owned storage at `data/chroma_db/`, distinct from the embedding cache and manifest. Keep one ingestion writer at a time and test persistence by reopening the database in a new process. Document backup/restore of the database directory together with its active-collection pointer while writers are stopped. Pin compatible `chromadb` dependencies and verify installation on the developer machine. A future multi-process service deployment can use Chroma's server/client mode as a separate enhancement.

## 11. Checkpoints, refresh, and failure behavior

Track each page revision through `discovered → collected → parsed → normalized → chunked → embedded → indexed → validated`, with per-stage hashes, processing versions, artifact paths, counts, timestamps, and errors. Use atomic artifact writes and SQLite transactions; allow one ingestion writer at a time.

`--resume` continues from verified completed stages. An unchanged revision with unchanged processing settings skips downstream work; changed parsing/chunking/model settings invalidate the appropriate stages. A failed embedding/index batch resumes without repeating successful embedding work. `--force` rechecks/reprocesses selected sources while still allowing an identical embedding-input cache hit.

Refresh is on demand, with a proposed 30-day recheck reminder. Track both source revision time and last successful check. A timeout must not delete a previously valid page. On partial collection failure, preserve raw successful work but do not publish a supposedly complete new four-city snapshot. Confirmed missing pages are reported explicitly and removed only through a validated replacement snapshot. Report stale retained content and unresolved coverage gaps.

## 12. Commands and configuration

These commands are implemented. See the root README for installation, `TRIPRADAR_` environment overrides, and verification results.

```bash
tripradar-ingest health
tripradar-ingest setup-model
tripradar-ingest health --check-embeddings
tripradar-ingest sources list
tripradar-ingest collect --destination lisbon --root-only
tripradar-ingest collect --all
tripradar-ingest parse --all
tripradar-ingest normalize --all
tripradar-ingest chunk --all
tripradar-ingest embed --all
tripradar-ingest index --all
tripradar-ingest ingest --all
tripradar-ingest ingest --all --resume
tripradar-ingest ingest --destination lisbon --force
tripradar-ingest ingest --all --dry-run
tripradar-ingest validate
tripradar-ingest stats
tripradar-ingest sources stale --days 30
tripradar-ingest health
tripradar-ingest search "public transport from the airport" --destination lisbon --section get_in --top-k 5
```

`normalize` includes cleaning and exact deduplication. Collection, parsing, and normalization work without downloaded model assets or a Chroma database. `setup-model` downloads and verifies the local model/tokenizer assets once; chunking, embedding, and search then use the cache. `--dry-run` displays scope/stages and local readiness without downloads or writes. `health` reports model-cache availability, runtime readiness, database-path access, and collection compatibility without downloading assets or running inference. `health --check-embeddings` runs one local embedding and verifies 384 dimensions; if assets are missing, it directs the user to `setup-model`. Reports distinguish a single-city run from complete four-city ingestion.

Settings cover data paths, source endpoint, User-Agent/contact, HTTP limits, district bounds, retry policy, local embedding-function/model identity, model/tokenizer checksums, formatting policy, embedding-space version, dimension, batch size, chunk budget/overlap, Chroma persistence path, collection name, and staleness interval. `.env.example` contains local settings and optional LangSmith credential placeholders. Never log secrets or full vectors.


Proposed `.env.example` values (confirm pinned model/runtime settings during implementation; supply a LangSmith key locally only when enabling tracing):

```dotenv
TRIPRADAR_EMBEDDING_FUNCTION=chroma_default
TRIPRADAR_EMBEDDING_MODEL=all-MiniLM-L6-v2
TRIPRADAR_EMBEDDING_DIMENSION=384
TRIPRADAR_EMBEDDING_BATCH_SIZE=32
TRIPRADAR_EMBEDDING_SPACE_VERSION=chroma-minilm-v1
TRIPRADAR_CHUNK_TARGET_TOKENS=180
TRIPRADAR_CHUNK_OVERLAP_TOKENS=24
TRIPRADAR_CHUNK_MAX_INPUT_TOKENS=256
TRIPRADAR_CHROMA_PERSIST_DIRECTORY=data/chroma_db
TRIPRADAR_CHROMA_COLLECTION=tripradar_destinations
TRIPRADAR_HTTP_TIMEOUT_SECONDS=30
TRIPRADAR_HTTP_MAX_RETRIES=4
TRIPRADAR_SAVE_EMBEDDINGS_DEBUG=false
LANGSMITH_TRACING=false
LANGSMITH_API_KEY=
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_PROJECT=tripradar-ingestion
LANGSMITH_WORKSPACE_ID=
LANGSMITH_HIDE_INPUTS=true
LANGSMITH_HIDE_OUTPUTS=true
```

Resolve these application settings explicitly into the adapters; the `CHROMA_*` and `EMBEDDING_*` entries above are application configuration, not assumed SDK auto-configuration. Validate that `EMBEDDING_MODEL` matches the pinned `DefaultEmbeddingFunction`; it is not an arbitrary model selector. Missing model assets block chunking/embedding/search; an inaccessible or incompatible Chroma database blocks publication/search. Never silently switch embedding models.

## 13. Retrieval contract for future agents

Implement a Python retrieval function and CLI first, with the future-compatible signature:

```text
search_guide(destination, section=None, query=..., k=5)
```

Normalize the destination, enforce destination and optional section filters, embed the query with the index's exact model/settings, and query only the validated active collection. Return text, chunk/document IDs, destination, district, section path, source/revision/history URLs, revision date, retrieval time, attribution/license, and similarity information.

Return Chroma cosine distance with lower-is-better ranking; if exposing similarity, label `score = 1 - distance` explicitly. Verify this contract using known vectors against the pinned client. Scores are not confidence or probabilities. Unknown destinations and empty/missing sections return a clear coverage result without falling back to another city. Calibrate any low-relevance cutoff using the retrieval evaluation set; top-k alone is not evidence of relevance.

The later agent must cite only returned evidence and report insufficient support. A retrieved `sleep` passage can support neighborhood/accommodation guidance, but cannot substantiate live hotel availability or the final $2,000 budget verdict. Dated weather and live offer evidence will have separate provider result IDs and timestamps in the future runtime layer.

## 14. Validation and acceptance criteria

Use small real attributed fixtures once collected, plus synthetic malformed/retry cases. Unit tests run offline with mocked Chroma embedding, storage, and tokenizer boundaries; they never download assets or export traces. Mark Wikimedia, model download, local inference, persistent Chroma, and LangSmith integration tests separately. Cached local inference/storage tests must work with network access disabled.

Required checks:

1. All four canonical root pages produce preserved raw content, usable normalized records, chunks, vectors, and traceable search results. District coverage/caps and absent sections are reported honestly.
2. Redirects, New York aliases, API errors inside HTTP 200, retry limits, missing pages, and pagination are handled correctly.
3. Nested sections are not double-counted; listing names/descriptions/hours/prices survive parsing; unknown templates produce inspectable diagnostics.
4. Every chunk has nonempty text, a valid parent, deterministic ID, source revision attribution, and a model-compatible token count. Every document/query embedding and Chroma collection must have exactly 384 dimensions. No silent truncation, duplicate IDs, NaN/Infinity, or dimension mismatches.
5. Repeating an unchanged run adds no duplicate vectors and performs no new document embeddings. A changed/deleted chunk disappears from active retrieval after a successful refresh. Failed publication leaves the prior snapshot intact.
6. Resume after interrupted collection/embedding/indexing completes successfully with matching manifests, files, and active vector counts.
7. Retrieval respects Chroma destination/section metadata filters and returns the exact stored citation text. Unsupported destination/section cases return coverage failures.
8. Mock missing/corrupt model assets, inference failures, incomplete/misaligned batches, nonfinite/incorrect-size vectors, and Chroma path-permission, storage, and schema failures. Reject incompatible collections and preserve resumability.
9. Reopen Chroma in a new process and verify persisted counts, documents, metadata, and retrieval. Ensure TripRadar uses its own database directory. Test that supplied cached vectors avoid duplicate inference, and that automatic text embedding and direct invocation use the same model and produce compatible retrieval results.
10. Verify trace nesting, stage counters, retry/error visibility, redaction, and resume correlation with a mocked LangSmith client. Disabling tracing or an exporter outage must not alter ingestion results. An explicitly enabled LangSmith integration test must show one complete run with local embedding and Chroma indexing child spans and a link in the local report.

Create 16 manually reviewed positive retrieval queries, four per city, covering transport, attractions/activities, food, and accommodation guidance. Annotate expected supporting passages after inspecting collected content. Initial target: a relevant passage in the top five for at least 13 of 16 queries, with 100% correct destination filtering and source linkage. Include additional negative/unsupported queries to test abstention. Tune chunking and query formatting using this set before changing the embedding model or adding a reranker.

Generate `data/reports/<run_id>.json` plus a readable summary containing attempted/succeeded/failed pages, per-city/section coverage, listing counts, unknown-template counts, excluded content, chunk token distribution, embedding/cache counts, local inference duration and tokenizer-measured input counts, embedding-space fingerprint, active vector counts, duration, and retrieval evaluation results. Do not invent expected page/chunk totals before real collection.

## 15. Implementation sequence after review

1. Scaffold `src/tripradar_ingestion/`, configuration, schemas, source registry, manifest, CLI, observability adapter, and project tooling directly under the parent project root. Instrument each stage as it is implemented. Reconcile outdated destinations, package locations, and embedding/vector-store references in `Trip-Planner-prompts/IMPLEMENTATION.md`, `Trip-Planner-prompts/AGENTS.md`, and `Trip-Planner-prompts/TRIPRADAR.md` with this plan as part of that later change.
2. Build and inspect Lisbon root collection, raw preservation, section/listing parsing, normalization, and coverage reports.
3. Set up the local Chroma embedding model and project-owned database directory, verify persistence and one 384-dimensional embedding, then complete the Lisbon vertical slice: token-safe chunks → Chroma local embeddings → Chroma persistence → cited semantic search.
4. Add Paris, London, New York City, and bounded district coverage using the same configurable collector.
5. Finish incremental refresh, cache reuse, staged publication, restart behavior, and source-attribution exports.
6. Run offline tests and enabled integration/evaluation checks. Document exact setup/collection/search commands, measured counts, gaps, and any untested external interactions.

Review defaults: Chroma local `all-MiniLM-L6-v2` embeddings (384d), persistent Chroma DB, four configured cities with bounded district expansion, section-aware token-limited chunks, and independently written ingestion code. No further architecture decision is required to begin once the user has reviewed this plan.

## 16. Ingestion observability with LangSmith

Use LangSmith to inspect the execution path from collection through validated Chroma publication. Its SDK supports custom Python function instrumentation through `@traceable` and trace contexts, so this pipeline does not require LangChain, LangGraph, or agents to gain tracing. Instrument the Wikivoyage HTTP collector, local Chroma embedding function, and Chroma storage adapter explicitly; enabling an environment variable alone will not trace arbitrary HTTP/database operations. See [LangSmith custom instrumentation](https://docs.langchain.com/langsmith/annotate-code).

### Trace structure

Create one root trace for each CLI invocation, with nested spans that reflect the actual execution order. Proposed full-run structure:

```text
tripradar.ingest                         run ID, scope, overall outcome
  configuration.validate
  sources.discover
  destination.process                   one per city
    page.process                        one per root/district article
      wikivoyage.collect                HTTP attempts and raw preservation
      wikitext.parse
      content.normalize
        content.clean
        content.deduplicate
      content.chunk
  embeddings.process
    chroma.embed_batch                  one per uncached local batch
  chroma.build_snapshot
    chroma.upsert_batch
    chroma.validate_snapshot            readback, counts, filters, test queries
    chroma.publish_snapshot             active-generation pointer switch
  report.write
```

Standalone `collect`, `chunk`, `embed`, and `index` commands receive their own root traces with the applicable children. Use stage spans for deterministic work, embedding spans for local inference, and retrieval spans for semantic searches where supported by the pinned SDK. Do not label collection, chunking, or upserts as LLM calls. Propagate parent context if concurrency is introduced. Prefer batch summaries to a separate span for every chunk.

### What each stage reports

| Stage | Observable information |
| --- | --- |
| Collection | City/page/revision, HTTP status, latency, bytes, retry attempts, raw artifact reference, unchanged/missing/failed outcome |
| Parsing | Sections/listings extracted, unknown templates, parse failures |
| Cleaning/normalization | Input/output records and characters, rejected records/reasons, exact duplicates removed, coverage gaps |
| Chunking | Chunk count, min/median/p95/max tokens, oversized/split inputs, chunker version |
| Local Chroma embedding | Model, batch ID, input count, cache hits/misses, inference latency, tokenizer-measured input tokens, dimension-validation failures |
| Chroma indexing | Collection/generation, submitted/acknowledged/verified record counts, batch latency, retries, document/metadata readback failures |
| Publication | Previous/new generation, validation outcome, publication success/failure |
| Overall run | Duration, completed/failed/skipped stages, per-city coverage, final outcome, report path |

Attach `ingestion_run_id`, `attempt_id`, destination ID, page/revision IDs where applicable, stage, batch ID, pipeline version, and embedding-space fingerprint as allowlisted metadata. Include environment and stage tags for filtering. LangSmith documents [metadata and tags](https://docs.langchain.com/langsmith/add-metadata-tags) for correlating and finding traces. A resumed invocation gets a new trace and attempt ID linked to the original logical ingestion run; completed cache hits are recorded as skipped/reused work.

Record failures even when the pipeline catches them to continue other cities. The root summary must explicitly say `success`, `partial_failure`, or `failed`, with failure counts, rather than treating a caught exception as a successful ingestion. Distinguish an acknowledged upsert from verified stored records and successful publication. Record local inference time and token counts as metadata. Do not present them as provider-billed tokens or invent embedding API charges. Optional LangSmith usage remains separate.

### Setup and operational behavior

Add the `langsmith` SDK dependency and centralize tracing in `observability.py`. Enable with `LANGSMITH_TRACING=true`, a locally supplied API key, and project `tripradar-ingestion`. Configure the endpoint for the account's region and workspace ID when required. The example defaults tracing to false until configured; once enabled, trace every run in this four-city MVP. Ordinary unit tests and `--dry-run` must not export traces.

Send only useful summaries by default: counts, IDs, timings, hashes, and sanitized errors. Keep raw guide payloads and embedding vectors in the local data artifacts. Hide function inputs/outputs through the client settings and explicitly sanitize metadata/errors as well; hiding inputs alone does not redact other trace fields. Never send API keys, authorization headers, or full vectors. LangSmith provides [input/output masking and processing hooks](https://docs.langchain.com/langsmith/mask-inputs-outputs).

Keep console progress, structured JSONL logs at `data/reports/<run_id>/events.jsonl`, manifests, and final reports operational when LangSmith is disabled or unreachable. An export failure produces a local warning and telemetry status; it must not retry successful ingestion stages or change publication outcomes. Use the pinned SDK's supported flush/shutdown mechanism on CLI exit, with bounded waiting. Include the trace ID/URL when available and indicate if delivery was unconfirmed; never fabricate a dashboard link.

In LangSmith, open the `tripradar-ingestion` project, find the invocation by run metadata, and expand its nested trace to identify slow or failed stages. Document an example successful run, a local embedding failure, and a Chroma indexing failure after implementation. LangSmith's [trace viewer](https://docs.langchain.com/langsmith/view-traces) provides the inspection interface. Database/process CPU, disk, memory, and storage health still require local process/filesystem diagnostics; application traces cover calls and observed outcomes. Keep LangSmith retention/usage limits separate from the durable ingestion ledger.

## 17. Planning-stage verification (historical)

Reviewed the TripRadar specifications and the earlier project’s structure/configuration references. The browsing tool could not open the supplied raw Lisbon API URL; no successful API collection or verified four-city payload is claimed. The revised plan was checked against official Chroma documentation for default local embeddings, persistence, supplied vectors, collection configuration, and filtering, plus the MiniLM model card. At the planning stage no model had been downloaded, database created, or inference run. Implementation has since exercised those operations; see the current measured results in `docs/validation.md`.

## 18. Implementation notes

- Ingestion environment overrides use `TRIPRADAR_` prefixes so legacy provider variables in the existing `.env` cannot select a different model/dimension. LangSmith retains `LANGSMITH_*` names. See the root `.env.example`.
- Reference documents are currently under `Trip-Planner-prompts/`; implementation remains at the parent root.
- Model files and checksums are stored in `data/models/`; `setup-model` is the only automatic model-download command.
- District discovery uses hierarchy-template name/items fields, including Paris arrondissements and New York boroughs. Missing district pages are explicit collection failures; no partial replacement is published.
- Read README.md and docs/validation.md for implemented behavior, real corpus counts, test results, and any remaining evaluation or live-tracing limitations. Historical planning verification notes above do not describe current execution status.

- Completed live collection, model setup, publication, and LangSmith readback. See `docs/validation.md` for the actual 93-page corpus, 9,289-vector index, tests, and retrieval limitations.
- Chunks now reference immutable normalized archives as well as raw revision files; validation checks their offsets and source checksums.
