"""Copy a published local snapshot to Cloud without recomputing embeddings."""

import os

import numpy as np
from dotenv import dotenv_values

from .config import Settings
from .embeddings import LocalEmbedder
from .utils import write_json, writer_lock
from .vectorstore import VectorStore


def copy_records(source, target, batch_size: int = 100) -> int:
    """Idempotent batches, with complete document/metadata/vector readback."""
    if batch_size < 1:
        raise ValueError("Batch size must be positive")
    total = source.count()
    if not total:
        raise ValueError("Cannot migrate an empty collection")
    verified = 0
    for offset in range(0, total, batch_size):
        batch = source.get(
            limit=batch_size, offset=offset, include=["documents", "metadatas", "embeddings"]
        )
        target.upsert(
            ids=batch["ids"],
            documents=batch["documents"],
            metadatas=batch["metadatas"],
            embeddings=batch["embeddings"],
        )
        actual = target.get(ids=batch["ids"], include=["documents", "metadatas", "embeddings"])
        positions = {value: i for i, value in enumerate(actual["ids"])}
        for i, value in enumerate(batch["ids"]):
            if value not in positions:
                raise ValueError("Cloud readback is missing records")
            j = positions[value]
            for field in ("documents", "metadatas"):
                if batch[field][i] != actual[field][j]:
                    raise ValueError(f"Cloud {field} readback mismatch")
            if not np.allclose(
                batch["embeddings"][i], actual["embeddings"][j], rtol=1e-5, atol=1e-6
            ):
                raise ValueError("Cloud embedding readback mismatch")
            verified += 1
    if source.count() != total or target.count() != total or verified != total:
        raise ValueError("Collection count changed or target contains extra records")
    return verified


def migrate_cloud(*, dry_run: bool = False) -> dict:
    import chromadb

    settings = Settings.load()
    env = {**dotenv_values(settings.root / ".env"), **os.environ}
    required = ("CHROMA_API_KEY", "CHROMA_TENANT", "CHROMA_DATABASE")
    missing = [key for key in required if not (env.get(key) or "").strip()]
    with writer_lock(settings.data):
        store = VectorStore(settings, LocalEmbedder(settings))
        source = store.active()
        report = {
            "source": source.name,
            "collection": "cloud_" + source.name,
            "records": source.count(),
            "missing_settings": missing,
            "dry_run": dry_run,
        }
        if dry_run:
            return report
        if missing:
            raise ValueError("Set these in local .env: " + ", ".join(missing))
        store.validate_active()
        client = chromadb.CloudClient(
            api_key=env["CHROMA_API_KEY"],
            tenant=env["CHROMA_TENANT"],
            database=env["CHROMA_DATABASE"],
        )
        metadata = {
            "tripradar_source": source.name,
            "fingerprint": store.fingerprint,
            "dimension": 384,
        }
        target = client.get_or_create_collection(
            report["collection"],
            embedding_function=None,
            metadata=metadata,
            schema=chromadb.Schema().create_index(
                config=chromadb.VectorIndexConfig(space="cosine")
            ),
        )
        if target.metadata != metadata:
            raise ValueError("Cloud collection already exists with incompatible metadata")
        report["verified_records"] = copy_records(
            source, target, min(100, client.get_max_batch_size())
        )
        report["status"] = "verified"
        write_json(settings.data / "reports/cloud_migration.json", report)
        return report
