from pathlib import Path

import numpy as np
import pytest

from tripradar_ingestion.config import Settings
from tripradar_ingestion.models import Page
from tripradar_ingestion.utils import digest


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path, http_interval_seconds=0, http_max_retries=1)


@pytest.fixture
def page():
    return Page(
        destination_id="lisbon",
        country="PT",
        requested_title="Lisbon",
        title="Lisbon",
        page_id=123,
        revision_id=456,
        revision_time="2026-01-01T00:00:00Z",
        retrieved_at="2026-01-02T00:00:00Z",
        source_url="https://en.wikivoyage.org/wiki/Lisbon",
        revision_url="https://en.wikivoyage.org/w/index.php?oldid=456",
        history_url="https://en.wikivoyage.org/wiki/Lisbon?action=history",
        raw_path="fixture.wiki",
        raw_hash="fixture",
        wikitext="A city guide.",
    )


class FakeEmbedder:
    fingerprint = "test-embedding-v1"
    function = None

    def __init__(self):
        self.cache = {}
        self.calls = 0

    def count(self, text):
        return len(text.split()) + 2

    def encode(self, texts):
        self.calls += len(texts)
        vectors = []
        for text in texts:
            vector = np.zeros(384, dtype=np.float32)
            for word in text.lower().split():
                vector[int(digest(word)[:8], 16) % 384] += 1
            vector /= np.linalg.norm(vector)
            vectors.append(vector)
        return np.asarray(vectors)

    def cached(self, text):
        return self.cache.get(text)

    def embed_chunks(self, chunks, obs):
        missing = list(
            dict.fromkeys(c.embedding_input for c in chunks if c.embedding_input not in self.cache)
        )
        if missing:
            for text, vector in zip(missing, self.encode(missing), strict=True):
                self.cache[text] = vector
        return {"embedded": len(missing)}

    @staticmethod
    def validate(vectors, count):
        from tripradar_ingestion.embeddings import LocalEmbedder

        return LocalEmbedder.validate(vectors, count)


@pytest.fixture
def embedder():
    return FakeEmbedder()


@pytest.fixture
def root_settings(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    source = Path(__file__).resolve().parents[1] / "config/destinations.yaml"
    (config / "destinations.yaml").write_text(source.read_text())
    return Settings(root=tmp_path, http_interval_seconds=0, http_max_retries=0)
