# Ingestion operations

Run commands from the parent project root or set `TRIPRADAR_ROOT`. `config/destinations.yaml` is the source registry; add a stable lowercase ID, Wikivoyage title, country, aliases, and optional `districts` list to add a city. Source access is restricted to the English Wikivoyage Action API.

Raw responses, extracted wikitext, response hashes, revision/fetch times, and URLs are stored before transformation. The section JSONL files preserve listing fields and unknown template diagnostics. Normalization records empty-section exclusions in each run's report folder. `stats` summarizes section coverage, chunk sizes, collection bounds, and the active snapshot.

SQLite records stage fingerprints and artifact checksums. A stage's inputs, processing version, or model/chunk settings changing invalidates its checkpoint. Before embedding/publication the pipeline checks the preceding artifact chain. Do not hand-edit generated JSONL and expect it to remain valid; rerun the necessary stages.

For interruptions, repeat the original command with `--resume`, including its `--destination` or `--all` and `--root-only` scope. Only one writer is allowed. A killed process releases the OS lock automatically. Successful API responses and model batches are reusable. A failed district collection does not replace that city's complete collected snapshot. Confirmed missing pages remain explicit failures until registry/source coverage is corrected and collection succeeds.

Typical troubleshooting:

- Missing local model: run `setup-model`, then `health --check-embeddings`.
- HTTP 429/503/maxlag: allow retries to finish; the collector honors Retry-After. Increase `TRIPRADAR_HTTP_INTERVAL_SECONDS` for repeated runs. Do not parallelize around rate limits.
- Empty/unsupported query scope: inspect `stats`, source coverage and configured aliases. There is no fallback to another city.
- Stale artifacts: run the named stage and its successors, or `ingest`.
- Incompatible collection fingerprint: rebuild with a matching model/chunker, preserving the old collection until the new one validates.
- Chroma directory not writable: check `TRIPRADAR_CHROMA_PERSIST_DIRECTORY`; local mode uses no server or credentials.
- Editable package import fails on macOS: Python ignores hidden `.pth` files. Use the documented `PYTHONPATH=src` module command or clear the hidden flag on the environment's editable `.pth` file.

To restore a backup, stop writers, restore the Chroma folder together with its active pointer/snapshot and cached embeddings, then run `validate`. Old generation collections are intentionally retained; database reset and pruning are not automatic.
