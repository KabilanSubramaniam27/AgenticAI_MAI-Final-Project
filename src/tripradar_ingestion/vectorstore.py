"""Validated snapshot publication; a failed build cannot replace the active corpus."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .chunker import VERSION
from .config import Settings
from .models import Chunk
from .observability import Observer
from .utils import digest, file_hash, read_json, read_jsonl, write_json


class VectorStore:
    def __init__(self, settings: Settings, embedder):
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self.settings, self.embedder = settings, embedder
        self.client = chromadb.PersistentClient(
            path=str(settings.resolve(settings.chroma_persist_directory)),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.pointer = settings.data / "manifests/active_collection.json"
        self.fingerprint = digest(
            [
                embedder.fingerprint,
                VERSION,
                settings.chunk_target_tokens,
                settings.chunk_overlap_tokens,
                settings.chunk_max_input_tokens,
            ]
        )

    def active(self):
        if not self.pointer.exists():
            raise ValueError("No published corpus; run ingest first")
        state = read_json(self.pointer)
        if state["fingerprint"] != self.fingerprint:
            raise ValueError(
                "Active collection uses incompatible model/chunk settings; rebuild index"
            )
        collection = self.client.get_collection(
            state["collection"], embedding_function=self.embedder.function
        )
        if (collection.metadata or {}).get("fingerprint") != self.fingerprint:
            raise ValueError("Collection fingerprint mismatch")
        return collection

    def validate_collection(self, collection, chunks: list[Chunk]) -> dict:
        expected = {c.chunk_id: c for c in chunks}
        if len(expected) != len(chunks) or collection.count() != len(expected):
            raise ValueError("Vector count or duplicate chunk mismatch")
        archives: dict[str, dict] = {}
        raw_hashes: dict[str, str] = {}
        for chunk in chunks:
            artifact = chunk.metadata.get("normalized_artifact")
            if artifact:
                key = str(artifact)
                if key not in archives:
                    rows = read_jsonl(Path(key))
                    if digest(rows) != chunk.metadata["normalized_artifact_hash"]:
                        raise ValueError("Normalized provenance archive was modified")
                    archives[key] = {r["document_id"]: r for r in rows}
                section = archives[key][chunk.document_id]
                if section["text"][chunk.start : chunk.end] != chunk.text:
                    raise ValueError("Chunk offsets do not match normalized provenance")
                raw = str(chunk.metadata["raw_path"])
                if raw not in raw_hashes:
                    raw_hashes[raw] = file_hash(Path(raw))
                if raw_hashes[raw] != chunk.metadata["raw_hash"]:
                    raise ValueError("Raw source checksum mismatch")
        seen = set()
        for offset in range(0, len(chunks), 200):
            result = collection.get(
                limit=200, offset=offset, include=["documents", "metadatas", "embeddings"]
            )
            self.embedder.validate(result["embeddings"], len(result["ids"]))
            for index, chunk_id in enumerate(result["ids"]):
                if chunk_id not in expected:
                    raise ValueError("Unknown vector ID")
                chunk = expected[chunk_id]
                if result["documents"][index] != chunk.text:
                    raise ValueError("Stored citation text mismatch")
                if result["metadatas"][index] != chunk.metadata:
                    raise ValueError("Stored metadata mismatch")
                seen.add(chunk_id)
        if seen != set(expected):
            raise ValueError("Incomplete readback")
        for city in sorted({c.metadata["destination_id"] for c in chunks}):
            chunk = next(c for c in chunks if c.metadata["destination_id"] == city)
            query = collection.query(
                query_embeddings=[self.embedder.cached(chunk.embedding_input)],
                where={"destination_id": city},
                n_results=1,
                include=["metadatas"],
            )
            if not query["ids"][0] or query["metadatas"][0][0]["destination_id"] != city:
                raise ValueError("Destination-filter smoke check failed")
        return {"verified_records": len(seen)}

    def publish(self, chunks: list[Chunk], obs: Observer) -> dict:
        if not chunks:
            raise ValueError("Refusing to publish an empty corpus")
        content_id = digest(
            [self.fingerprint, sorted((c.chunk_id, digest(c.metadata)) for c in chunks)]
        )
        name = f"{self.settings.chroma_collection}_{content_id[:16]}"
        with obs.span("chroma.build_snapshot", collection=name) as summary:
            collection = self.client.get_or_create_collection(
                name,
                embedding_function=self.embedder.function,
                metadata={"fingerprint": self.fingerprint, "dimension": 384},
                configuration={"hnsw": {"space": "cosine"}},
            )
            if (collection.metadata or {}).get("fingerprint") != self.fingerprint:
                raise ValueError("Staging collection incompatible")
            size = min(200, self.client.get_max_batch_size())
            for offset in range(0, len(chunks), size):
                batch = chunks[offset : offset + size]
                vectors = [self.embedder.cached(c.embedding_input) for c in batch]
                if any(v is None for v in vectors):
                    raise ValueError("Missing embedding cache; run embed before index")
                self.embedder.validate(vectors, len(batch))
                with obs.span(
                    "chroma.upsert_batch", batch_id=offset // size, submitted=len(batch)
                ) as metrics:
                    collection.upsert(
                        ids=[c.chunk_id for c in batch],
                        embeddings=vectors,
                        documents=[c.text for c in batch],
                        metadatas=[c.metadata for c in batch],
                    )
                    metrics["acknowledged"] = len(batch)
            with obs.span("chroma.validate_snapshot") as metrics:
                metrics.update(self.validate_collection(collection, chunks))
            with obs.span("chroma.publish_snapshot"):
                previous = read_json(self.pointer)["collection"] if self.pointer.exists() else None
                # Snapshot artifact is the authoritative validation input, not mutable stage files.
                snapshot = self.settings.data / "manifests" / (name + ".json")
                write_json(snapshot, [c.model_dump() for c in chunks])
                write_json(
                    self.pointer,
                    {
                        "collection": name,
                        "previous": previous,
                        "fingerprint": self.fingerprint,
                        "snapshot": str(snapshot),
                        "count": len(chunks),
                        "run_id": obs.run_id,
                    },
                )
            summary.update(collection=name, vectors=len(chunks))
        return {"collection": name, "vectors": len(chunks), "fingerprint": self.fingerprint}

    def validate_active(self) -> dict:
        collection = self.active()
        state = read_json(self.pointer)
        chunks = [Chunk.model_validate(row) for row in read_json(Path(state["snapshot"]))]
        return self.validate_collection(collection, chunks)

    def search(
        self, destination: str, query: str, section: str | None, k: int, obs: Observer
    ) -> list[dict[str, Any]]:
        collection = self.active()
        where = (
            {"$and": [{"destination_id": destination}, {"section": section}]}
            if section
            else {"destination_id": destination}
        )
        if not collection.get(where=where, limit=1)["ids"]:
            return []
        with obs.span("chroma.embed_query", run_type="embedding"):
            vector = self.embedder.encode([query])
        with obs.span("chroma.search", run_type="retriever", destination_id=destination) as metrics:
            rows = collection.query(
                query_embeddings=vector,
                where=where,
                n_results=min(k, collection.count()),
                include=["documents", "metadatas", "distances"],
            )
            results = [
                {
                    "text": text,
                    **meta,
                    "distance": distance,
                    "score": 1 - distance,
                    "metric": "cosine",
                    "score_kind": "similarity_not_confidence",
                }
                for text, meta, distance in zip(
                    rows["documents"][0], rows["metadatas"][0], rows["distances"][0], strict=True
                )
            ]
            metrics["returned"] = len(results)
            return results
