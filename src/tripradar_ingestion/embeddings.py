"""Chroma's local MiniLM model, guarded against hidden downloads and truncation."""

from __future__ import annotations

import io
import tarfile
from importlib.metadata import version
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

from .config import Settings
from .models import Chunk
from .observability import Observer
from .utils import atomic_bytes, digest, file_hash, read_json, write_json


class LocalEmbedder:
    def __init__(self, settings: Settings):
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

        self.settings = settings
        # Pinned Chroma backend stores its model here; no writes to the user's global cache.
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = settings.data / "models/all-MiniLM-L6-v2"
        self.backend = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
        self.function = DefaultEmbeddingFunction()
        self.model_dir = Path(self.backend.DOWNLOAD_PATH) / self.backend.EXTRACTED_FOLDER_NAME
        self.receipt = settings.data / "models/verified.json"
        self._tokenizer: Tokenizer | None = None
        self._fingerprint: str | None = None

    def setup(self) -> dict:
        self.backend._download_model_if_not_exists()
        archive = Path(self.backend.DOWNLOAD_PATH) / self.backend.ARCHIVE_FILENAME
        if not archive.is_file() or file_hash(archive) != self.backend._MODEL_SHA256:
            raise RuntimeError("Model archive failed checksum verification")
        # Re-extract only from the verified archive, repairing damaged extracted files.
        with tarfile.open(archive, "r:gz") as bundle:
            bundle.extractall(self.backend.DOWNLOAD_PATH, filter="data")
        files = {p.name: file_hash(p) for p in self.model_dir.iterdir() if p.is_file()}
        write_json(self.receipt, {"files": files, "model": self.settings.embedding_model})
        self.ensure_ready()
        self.validate(self.function(["Travel guide model verification"]), 1)
        return {
            "model": self.settings.embedding_model,
            "dimension": 384,
            "model_directory": str(self.model_dir),
            "fingerprint": self.fingerprint,
        }

    def ensure_ready(self) -> None:
        if self._fingerprint:
            return
        if not self.receipt.is_file():
            raise RuntimeError("Model not set up; run tripradar-ingest setup-model")
        files = read_json(self.receipt)["files"]
        for name, expected in files.items():
            path = self.model_dir / name
            if not path.is_file() or file_hash(path) != expected:
                raise RuntimeError("Model assets missing/corrupt; run setup-model")
        if not {"model.onnx", "tokenizer.json"}.issubset(files):
            raise RuntimeError("Incomplete model receipt")
        self._fingerprint = digest(
            {
                "files": files,
                "chromadb": version("chromadb"),
                "model": self.settings.embedding_model,
                "space": self.settings.embedding_space_version,
                "dimension": 384,
                "format": "prefix-v1",
                "metric": "cosine",
            }
        )

    @property
    def fingerprint(self) -> str:
        self.ensure_ready()
        return str(self._fingerprint)

    @property
    def tokenizer(self):
        self.ensure_ready()
        if self._tokenizer is None:
            self._tokenizer = Tokenizer.from_file(str(self.model_dir / "tokenizer.json"))
            self._tokenizer.no_truncation()
            self._tokenizer.no_padding()
        return self._tokenizer

    def count(self, text: str) -> int:
        return len(self.tokenizer.encode(text).ids)

    @staticmethod
    def validate(vectors, count: int) -> np.ndarray:
        matrix = np.asarray(vectors, dtype=np.float32)
        if matrix.shape != (count, 384) or not np.isfinite(matrix).all():
            raise ValueError("Invalid embedding count, dimension, or nonfinite values")
        if (np.linalg.norm(matrix, axis=1) == 0).any():
            raise ValueError("Zero embedding")
        return matrix

    def encode(self, texts: list[str]) -> np.ndarray:
        self.ensure_ready()
        if any(
            not text.strip() or self.count(text) > self.settings.chunk_max_input_tokens
            for text in texts
        ):
            raise ValueError("Empty or oversized embedding input; maximum 256 model tokens")
        return self.validate(self.function(texts), len(texts))

    def cache_path(self, text: str) -> Path:
        return self.settings.data / "embeddings" / self.fingerprint / (digest(text) + ".npy")

    def cached(self, text: str) -> np.ndarray | None:
        path = self.cache_path(text)
        if path.is_file():
            try:
                return self.validate(np.load(path, allow_pickle=False).reshape(1, -1), 1)[0]
            except (ValueError, OSError):
                return None
        return None

    def embed_chunks(self, chunks: list[Chunk], obs: Observer) -> dict:
        texts = list(dict.fromkeys(c.embedding_input for c in chunks))
        missing = [text for text in texts if self.cached(text) is None]
        size = self.settings.embedding_batch_size
        for offset in range(0, len(missing), size):
            batch = missing[offset : offset + size]
            with obs.span(
                "chroma.embed_batch",
                run_type="embedding",
                batch_id=offset // size,
                input_count=len(batch),
            ) as summary:
                vectors = self.encode(batch)
                for text, vector in zip(batch, vectors, strict=True):
                    stream = io.BytesIO()
                    np.save(stream, vector, allow_pickle=False)
                    atomic_bytes(self.cache_path(text), stream.getvalue())
                summary.update(input_tokens=sum(self.count(t) for t in batch), dimension=384)
        return {
            "chunks": len(chunks),
            "unique_inputs": len(texts),
            "embedded": len(missing),
            "cache_hits": len(texts) - len(missing),
            "fingerprint": self.fingerprint,
        }
