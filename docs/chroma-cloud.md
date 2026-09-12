# Copy local data to Chroma Cloud

Create a database in your Chroma Cloud account and add its credentials to the ignored
local `.env` file (do not paste keys into source code or chat):

```dotenv
CHROMA_API_KEY=
CHROMA_TENANT=
CHROMA_DATABASE=
```

Use your actual database name; `Dev` is only an example. From the project root:

```bash
PYTHONPATH=src .venv/bin/python -m tripradar_ingestion.cli cloud-upload --dry-run
PYTHONPATH=src .venv/bin/python -m tripradar_ingestion.cli cloud-upload
```

The dry run is local and reports missing configuration without exposing credentials.
The upload validates the published local corpus, copies IDs, documents, all metadata
(including existing local provenance paths), and stored vectors in batches, and verifies
every record by reading it back. It does not regenerate embeddings. A separate
`cloud_<local-snapshot-name>` collection permits resuming interrupted uploads using
idempotent upserts. A failed run can leave a partial cloud collection; only a successful
verification writes `data/reports/cloud_migration.json`. No local collection is deleted.

After upload, open the matching tenant/database in the Chroma Cloud console and select
the collection named in the report. Python access uses `chromadb.CloudClient`; use
`get_collection(name, embedding_function=None)` and `get()` to inspect records. Semantic
queries must supply embeddings from the same local MiniLM model. The existing ingestion
and search commands continue to use local Chroma; upload again after a new ingestion
snapshot to copy that snapshot. Old cloud snapshots are retained.

References: [Cloud client](https://docs.trychroma.com/docs/run-chroma/clients),
[adding existing embeddings](https://docs.trychroma.com/reference/chroma-api/record/add-records).
