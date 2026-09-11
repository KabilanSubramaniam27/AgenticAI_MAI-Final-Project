import httpx
import pytest
import respx

from tripradar_ingestion.collector import API, Collector, SourceError
from tripradar_ingestion.models import Destination
from tripradar_ingestion.observability import Observer


def api_response(request):
    if request.url.params["action"] == "query":
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {
                            "pageid": 7,
                            "ns": 0,
                            "title": "Lisbon",
                            "revisions": [{"revid": 77, "timestamp": "2026-01-01T00:00:00Z"}],
                        }
                    ]
                }
            },
        )
    assert request.url.params["oldid"] == "77"
    return httpx.Response(200, json={"parse": {"revid": 77, "wikitext": "== See ==\nA museum."}})


@respx.mock
def test_pinned_collection_and_raw_cache(settings):
    route = respx.get(API).mock(side_effect=api_response)
    obs = Observer(settings, "test")
    collector = Collector(settings, obs)
    city = Destination(id="lisbon", title="Lisbon", country="PT")
    first = collector.page(city, "Lisbon")
    second = collector.page(city, "Lisbon")
    collector.close()
    assert route.call_count == 3  # two initial calls, then revision check only
    assert first.revision_id == second.revision_id == 77
    assert (
        (settings.data / "raw/wikivoyage/lisbon/7/77/source.wiki").read_text().startswith("== See")
    )


@respx.mock
def test_api_error_inside_200_is_failure(settings):
    respx.get(API).respond(200, json={"error": {"code": "missingtitle"}})
    collector = Collector(settings, Observer(settings, "test"))
    with pytest.raises(SourceError, match="missingtitle"):
        collector.request({"action": "parse"})
    collector.close()


@respx.mock
def test_rate_limit_retry(settings, monkeypatch):
    sleeps = []
    monkeypatch.setattr("tripradar_ingestion.collector.time.sleep", sleeps.append)
    route = respx.get(API).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    collector = Collector(settings, Observer(settings, "test"))
    assert collector.request({"action": "query"})[0] == {"ok": True}
    assert route.call_count == 2
    assert 7 in sleeps
    collector.close()
