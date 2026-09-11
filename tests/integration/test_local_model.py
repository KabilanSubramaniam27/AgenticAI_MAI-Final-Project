from pathlib import Path

import numpy as np
import pytest

from tripradar_ingestion.config import Settings
from tripradar_ingestion.embeddings import LocalEmbedder

pytestmark = pytest.mark.integration


def test_actual_local_embedding_no_download(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    if not (root / "data/models/verified.json").exists():
        pytest.skip("Run setup-model to enable cached local inference test")
    settings = Settings(root=root)
    embedder = LocalEmbedder(settings)
    monkeypatch.setattr(
        "httpx.stream", lambda *_args, **_kwargs: pytest.fail("Unexpected download")
    )
    vectors = embedder.encode(["A museum in Lisbon.", "A museum in Lisbon."])
    assert vectors.shape == (2, 384)
    np.testing.assert_allclose(vectors[0], vectors[1])
    assert np.isclose(np.linalg.norm(vectors[0]), 1)
    assert embedder.count("museum " * 400) > 256
    with pytest.raises(ValueError, match="oversized"):
        embedder.encode(["museum " * 400])


@pytest.mark.parametrize(
    "vectors",
    [np.zeros((1, 384)), np.ones((1, 4096)), np.full((1, 384), np.nan), np.full((1, 384), np.inf)],
)
def test_reject_invalid_vectors(vectors):
    with pytest.raises(ValueError):
        LocalEmbedder.validate(vectors, 1)
