from types import SimpleNamespace

import chromadb
import pytest

from tripradar_ingestion.cloud import copy_records


def test_cloud_copy_reuses_vectors_and_can_resume(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "db"))
    source = client.create_collection("source", embedding_function=None)
    target = client.create_collection("target", embedding_function=None)
    source.add(
        ids=["one", "two", "three"],
        documents=["Lisbon guide", "Paris guide", "London guide"],
        metadatas=[{"destination_id": city} for city in ("lisbon", "paris", "london")],
        embeddings=[[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]],
    )
    assert copy_records(source, target, batch_size=2) == 3
    assert copy_records(source, target, batch_size=2) == 3
    assert target.count() == 3
    target.add(ids=["extra"], documents=["Unrelated"], embeddings=[[1.0, 1.0]])
    with pytest.raises(ValueError, match="extra records"):
        copy_records(source, target)


def test_cloud_copy_detects_corrupt_readback(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "db"))
    source = client.create_collection("source", embedding_function=None)
    target = client.create_collection("target", embedding_function=None)
    source.add(
        ids=["one"], documents=["Guide"], metadatas=[{"city": "Paris"}], embeddings=[[1.0, 0.0]]
    )
    real_get = target.get

    def corrupt(**kwargs):
        result = real_get(**kwargs)
        result["documents"][0] = "Wrong text"
        return result

    proxy = SimpleNamespace(get=corrupt, upsert=target.upsert, count=target.count)
    with pytest.raises(ValueError, match="documents readback mismatch"):
        copy_records(source, proxy)
