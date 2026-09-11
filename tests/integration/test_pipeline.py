import httpx
import pytest
import respx

from tripradar_ingestion.pipeline import Pipeline
from tripradar_ingestion.registry import load_registry
from tripradar_ingestion.utils import read_json
from tripradar_ingestion.vectorstore import VectorStore

pytestmark = pytest.mark.integration


@respx.mock
def test_pipeline_idempotency_and_failure_preserves_active(root_settings, embedder):
    from tripradar_ingestion.collector import API

    cities = load_registry(root_settings.root)[:2]
    ids = {"Lisbon": 1, "Paris": 2}
    failed = set()

    def respond(request):
        params = request.url.params
        if params["action"] == "query":
            title = params["titles"]
            if title in failed:
                return httpx.Response(200, json={"error": {"code": "missingtitle"}})
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": ids[title],
                                "ns": 0,
                                "title": title,
                                "revisions": [
                                    {"revid": ids[title] * 10, "timestamp": "2026-01-01T00:00:00Z"}
                                ],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "parse": {
                    "revid": int(params["oldid"]),
                    "wikitext": "== See ==\nA city museum with paintings.\n== Eat ==\nLocal markets.",
                }
            },
        )

    route = respx.get(API).mock(side_effect=respond)
    pipeline = Pipeline(root_settings, embedder)
    first = pipeline.run(cities, root_only=True)
    assert not first["errors"]
    assert first["index"]["vectors"] == 4
    calls = embedder.calls
    second = pipeline.run(cities, root_only=True)
    assert not second["errors"]
    assert embedder.calls == calls
    assert second["index"]["collection"] == first["index"]["collection"]
    # A city-scoped index must preserve the other city.
    third = pipeline.run(cities[:1], stage="index", root_only=True)
    assert not third["errors"] and third["index"]["vectors"] == 4
    pointer = root_settings.data / "manifests/active_collection.json"
    old = read_json(pointer)["collection"]
    failed.add("Paris")
    failure = pipeline.run(cities, root_only=True)
    assert failure["outcome"] == "partial_failure"
    assert read_json(pointer)["collection"] == old
    failed.clear()
    before = route.call_count
    resumed = pipeline.run(cities, root_only=True, resume=True)
    assert resumed["run_id"] == failure["run_id"]
    assert resumed["attempt_id"] != failure["attempt_id"]
    assert not resumed["errors"]
    assert route.call_count - before == 1  # Only failed city's revision rechecked
    assert VectorStore(root_settings, embedder).validate_active()["verified_records"] == 4


@respx.mock
def test_index_refuses_changed_source_without_reprocessing(root_settings, embedder):
    from tripradar_ingestion.collector import API
    from tripradar_ingestion.utils import read_jsonl, write_jsonl

    city = load_registry(root_settings.root)[:1]
    respx.get(API).mock(
        side_effect=lambda request: (
            httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": 1,
                                "ns": 0,
                                "title": "Lisbon",
                                "revisions": [{"revid": 10, "timestamp": "2026-01-01T00:00:00Z"}],
                            }
                        ]
                    }
                },
            )
            if request.url.params["action"] == "query"
            else httpx.Response(
                200, json={"parse": {"revid": 10, "wikitext": "== See ==\nMuseum."}}
            )
        )
    )
    pipeline = Pipeline(root_settings, embedder)
    assert not pipeline.run(city, root_only=True)["errors"]
    source = pipeline.artifact("collect", "lisbon")
    rows = read_jsonl(source)
    rows[0]["wikitext"] += "\nNew content"
    write_jsonl(source, rows)
    report = pipeline.run(city, stage="index", root_only=True)
    assert report["errors"]
    assert "Stale or modified parse" in report["errors"][0]["message"]
