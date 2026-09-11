# Validation results

Verified on September 10, 2026 (America/New_York; source/run timestamps use UTC).

The implemented package completed real Wikivoyage collection, local Chroma MiniLM inference, persistent indexing, readback/provenance validation, source-attributed retrieval, and LangSmith trace readback. No agent, pricing, weather, or itinerary implementation is claimed.

## Published corpus

| Destination | Pages including districts | Chunks/vectors |
| --- | ---: | ---: |
| Lisbon | 7 | 491 |
| Paris | 22 | 1,591 |
| London | 29 | 3,911 |
| New York City | 35 | 3,296 |
| Total | **93** | **9,289** |

All configured hierarchy candidates within the depth/page limits were collected; no cap/depth exclusions were recorded in this run. This is bounded hierarchy coverage, not a claim to contain every destination attraction or every linked article.

Active collection: `tripradar_destinations_6d212e1068573a49`.

Each vector has 384 dimensions. Input-token distribution: minimum 10, median 111, p95 176, maximum 180 (below the 256-token application ceiling). Collection readback verified all 9,289 vector IDs, dimensions, finite values, documents, and metadata. Final validation also checked normalized archive hashes, exact chunk offsets, and raw source checksums. A separate CLI process reopened the persistent database successfully.

Source files are under `data/raw/wikivoyage/`, normalized revision artifacts under `data/normalized/archive/`, and the current snapshot/pointer under `data/manifests/`.

## Automated checks

- **26 tests passed**, including offline HTTP retry/API-error cases, nested sections/listings, unknown templates, short warnings, exact chunk coverage, oversized listing identity, environment isolation, tamper detection, writer locking, metadata filters, snapshot replacement, model mismatch, interrupted-run resume, unchanged-run idempotency, tracing failures, and real cached model inference.
- `ruff check src tests`: passed.
- `ruff format --check src tests`: passed.
- `mypy src`: passed for 18 source files.
- Installed `tripradar-ingest health --check-embeddings`: model checksums verified, local inference passed, active collection found.
- Installed `tripradar-ingest validate`: 9,289 records verified.

Python 3.12, Chroma 1.5.9 and LangSmith 0.12.4 were used; all resolved dependencies are recorded in `uv.lock`. The regular package installation (`uv sync --locked --no-editable`) avoids macOS hidden `.pth` flags observed with editable installs in this workspace.

The full live collector honored Wikimedia rate limits and Retry-After delays. Tests inject retry failures deterministically; they do not repeatedly exercise live failure modes.

## Retrieval check

`tripradar-ingest evaluate` scored **14/16** expected-phrase hits in the top five, exceeding the initial 13/16 target. The fixture has four queries per city, spanning transport, attractions, food, and accommodation. All results stayed within the selected destination/section and included revision URLs.

This is a small smoke evaluation using manually chosen supporting phrases, not a comprehensive semantic-relevance, factuality, or itinerary-quality benchmark. No calibrated rejection threshold or reranker is implemented. The two retained misses were:

- Paris: restaurant service/tipping guidance under the `eat` filter.
- London: Travelodge budget-chain accommodation under the `sleep` filter.

Review these coverage/ranking cases before relying on precise recommendations. The future agent must abstain when the retrieved text does not support its claim. Unknown destination and absent-section behavior are covered by explicit resolution/filter tests; the pipeline does not fall back to another city.

The detailed evaluation output remains at `data/reports/retrieval_evaluation.json`.

## Resume and tracing

Final successful attempt: `60332b4beadc4b5685a8d6b9237eaf72` under logical run `3038f2b893924b7f922a13ec847f992f`. It reused **all 9,289 cached embeddings**, generated zero new document embeddings, and published a validated snapshot. Earlier failed/debug attempts remain distinguishable by attempt ID in the append-only events.

LangSmith delivery was confirmed by server readback. [Open the full ingestion trace](https://smith.langchain.com/o/25780d77-08ee-41fa-8652-37ae6c96ee33/projects/p/7b059333-2c6f-4f58-8f02-9a95db1d8122/r/01a08e39-9775-75e3-80fc-e2b14e5ecbe3?poll=true) (requires access to the configured LangSmith workspace). The trace shows collection-stage reuse, parsing/normalization, chunking, embedding-cache summaries, Chroma upserts, readback/validation, and publication. A separate live local-embedding trace also reached LangSmith.

Ingestion is traced to `tripradar-ingestion` through `TRIPRADAR_LANGSMITH_PROJECT`, preserving the existing shared `.env` project and credentials. The local report is `data/reports/3038f2b893924b7f922a13ec847f992f.json`; step events are `data/reports/3038f2b893924b7f922a13ec847f992f/events.jsonl`.

## Operational limits

- Only English Wikivoyage and the four configured destinations/hierarchies were exercised.
- Guide listings can be stale; collecting a page is not verifying its prices, opening times, or availability.
- Unsupported templates are reported and retain inspectable raw references; their visible parameters are preserved, but full MediaWiki template expansion is not implemented.
- CPU/local Chroma was tested. Chroma Cloud/server deployment, distributed writers, scheduling, and automatic generation pruning are not included.
- Existing `.env` secrets were preserved; only the nonsecret TripRadar tracing-project override was added. No code was copied from the earlier project.
