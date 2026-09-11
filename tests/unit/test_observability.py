import json

import pytest

from tripradar_ingestion.observability import Observer


def test_local_spans_merge_metadata_and_record_failure(settings):
    obs = Observer(settings, "logical-run", "attempt")
    with pytest.raises(ValueError), obs.span("root"):
        with obs.span("child", collection="before") as summary:
            summary.update(collection="after")
            raise ValueError("secret should not be serialized")
    events = [json.loads(line) for line in obs.path.read_text().splitlines()]
    assert [e["stage"] for e in events] == ["root", "child", "child", "root"]
    assert events[-2]["collection"] == "after"
    assert events[-1]["outcome"] == "failed"
    assert "secret" not in obs.path.read_text()


def test_exporter_failure_cannot_change_work(settings, monkeypatch):
    obs = Observer(settings, "logical-run")
    obs.client = object()
    monkeypatch.setattr(
        "langsmith.run_trees.RunTree", lambda **_: (_ for _ in ()).throw(RuntimeError("offline"))
    )
    with obs.span("work") as summary:
        summary["completed"] = 3
    assert obs.events[-1]["completed"] == 3
    assert obs.telemetry == "unavailable"


def test_trace_url_uses_confirmed_run_object(settings):
    class Client:
        def flush(self):
            pass

        def read_run(self, run_id):
            assert run_id == "trace-id"
            return {"id": run_id}

        def get_run_url(self, *, run):
            assert run == {"id": "trace-id"}
            return "https://trace.example/confirmed"

    obs = Observer(settings, "logical-run")
    obs.client = Client()
    obs.trace_id = "trace-id"
    obs.close()
    assert obs.telemetry == "confirmed"
    assert obs.trace_url == "https://trace.example/confirmed"
