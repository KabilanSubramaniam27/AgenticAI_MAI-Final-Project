# Inspecting ingestion

Enable `LANGSMITH_TRACING`, supply `LANGSMITH_API_KEY`, and choose project `tripradar-ingestion` in `.env`. Use the correct regional `LANGSMITH_ENDPOINT` and workspace ID if required. These credentials are independent of Chroma, which runs locally. `TRIPRADAR_LANGSMITH_PROJECT` overrides a shared `LANGSMITH_PROJECT`; this workspace uses that override to keep ingestion traces in `tripradar-ingestion` without replacing existing credentials.

Every pipeline invocation has a root trace. Expand city/stage children to inspect request retries, page revisions, section/listing counts, unknown templates, empty sections, chunks, model-token budgets, cached versus newly generated vectors, and Chroma batch/readback/publication counts. Local embedding spans describe CPU inference, not paid LLM token usage.

A recovered HTTP failure is a retry event. An exhausted failure marks the source/city and overall run failed or partial, even when other cities continue. A Chroma validation failure prevents the active pointer changing. An unchanged rerun should show reused processing and zero new document embeddings. A resumed run shares `ingestion_run_id` and has a new `attempt_id`.

Inputs/outputs are hidden and errors are reduced to their types in external traces. Source titles and IDs, counts, and timings are visible. Raw text, vectors, and secrets stay out of tracing. Local errors in the run report can contain the source URL needed for debugging but never receive config objects or authorization headers.

`data/reports/<run_id>/events.jsonl` is append-only local stage history. `data/reports/<run_id>.json` contains the final outcome and telemetry status. A trace URL is included after SDK flush and server readback; unavailable export does not replay ingestion or change published data. CLI export waiting is bounded to five seconds. LangSmith's retention is not the durable ingestion ledger.

Use local process and filesystem tools for CPU, memory, and disk usage. LangSmith covers instrumented operation timings and outcomes, not operating-system resource telemetry.
