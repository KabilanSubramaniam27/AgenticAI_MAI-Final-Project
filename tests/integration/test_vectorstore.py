import pytest

from tripradar_ingestion.chunker import chunk_section
from tripradar_ingestion.normalizer import normalize
from tripradar_ingestion.observability import Observer
from tripradar_ingestion.parser import parse_page
from tripradar_ingestion.utils import read_json
from tripradar_ingestion.vectorstore import VectorStore

pytestmark = pytest.mark.integration


def make_chunks(page, settings, embedder, text):
    page.wikitext = "== See ==\n" + text
    section, _ = normalize(parse_page(page)[1])
    return chunk_section(section, embedder, settings)


def test_publish_filter_replace_and_failed_snapshot(settings, page, embedder, monkeypatch):
    obs = Observer(settings, "test")
    chunks = make_chunks(page, settings, embedder, "Lisbon city museum art exhibits.")
    other = page.model_copy(update={"destination_id": "paris", "page_id": 999, "title": "Paris"})
    chunks += make_chunks(other, settings, embedder, "Paris city museum art exhibits.")
    embedder.embed_chunks(chunks, obs)
    store = VectorStore(settings, embedder)
    initial = store.publish(chunks, obs)
    assert store.validate_active()["verified_records"] == 2
    hits = store.search("lisbon", "museum", "see", 5, obs)
    assert len(hits) == 1 and hits[0]["destination_id"] == "lisbon"
    assert store.search("lisbon", "hotel", "sleep", 5, obs) == []
    # A validation failure must never activate the new collection.
    updated = make_chunks(page, settings, embedder, "A replacement Lisbon gallery.")
    embedder.embed_chunks(updated, obs)
    with monkeypatch.context() as context:
        context.setattr(
            store,
            "validate_collection",
            lambda *_: (_ for _ in ()).throw(ValueError("injected failure")),
        )
        with pytest.raises(ValueError, match="injected"):
            store.publish(updated, obs)
    assert read_json(store.pointer)["collection"] == initial["collection"]
    store.publish(updated, obs)
    assert store.active().count() == 1
    assert not store.active().get(ids=[chunks[0].chunk_id])["ids"]
    reopened = VectorStore(settings, embedder)
    assert reopened.validate_active()["verified_records"] == 1


def test_incompatible_model_cannot_query(settings, page, embedder):
    obs = Observer(settings, "test")
    chunks = make_chunks(page, settings, embedder, "Museum.")
    embedder.embed_chunks(chunks, obs)
    VectorStore(settings, embedder).publish(chunks, obs)
    embedder.fingerprint = "different-space"
    with pytest.raises(ValueError, match="incompatible"):
        VectorStore(settings, embedder).active()
