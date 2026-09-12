import json
from types import SimpleNamespace
from uuid import uuid4

from pydantic import SecretStr

from tripradar_agents.config import Settings
from tripradar_agents.langsmith_export import Exporter, export_trace
from tripradar_agents.observability import Trace


def settings(**kwargs):
    return Settings(
        _env_file=None,
        mode="fixture",
        langsmith_tracing=True,
        langsmith_api_key=SecretStr("lsv2_pt_testcredential123456789"),
        **kwargs,
    )


class ClientDouble:
    def __init__(self, **kwargs):
        self.runs = []
        self.tracing_sample_rate = 1.0
        self._tracing_sample_rate = 1.0

    def create_run(self, **kwargs):
        self.runs.append(kwargs)

    def read_run(self, rid):
        return SimpleNamespace(id=rid)

    def get_run_url(self, **kwargs):
        return "https://smith.langchain.com/test-trace"


def test_real_run_tree_export_is_redacted_and_parented():
    rid, call = uuid4().hex, uuid4().hex
    start = "2026-09-12T12:00:00+00:00"
    end = "2026-09-12T12:00:01+00:00"
    secret = "lsv2_pt_syntheticSecret123456789"
    events = [
        {
            "event": "llm.input",
            "agent": "orchestrator",
            "call_id": call,
            "time": start,
            "messages": secret,
        },
        {
            "event": "llm.output",
            "agent": "orchestrator",
            "call_id": call,
            "time": end,
            "output": secret,
        },
        {"event": "agent.start", "agent": "itinerary_builder", "time": start},
        {
            "event": "tool.start",
            "agent": "itinerary_builder",
            "tool": "search_guide",
            "time": start,
        },
        {"event": "tool.end", "agent": "itinerary_builder", "tool": "search_guide", "time": end},
        {
            "event": "rag.end",
            "agent": "itinerary_builder",
            "query": "Lisbon",
            "time": end,
            "evidence_ids": ["g1"],
        },
    ]
    client = ClientDouble()
    url = export_trace(
        client,
        settings(),
        {
            "request_id": rid,
            "started": start,
            "ended": end,
            "input": {"thread_id": "session", "message": secret},
            "output": {"answer": secret},
            "events": events,
        },
    )
    assert url.endswith("test-trace")
    assert secret not in json.dumps(client.runs, default=str)
    assert len(client.runs) == 6
    assert {r["run_type"] for r in client.runs} == {"chain", "llm", "tool", "retriever"}
    root = next(r for r in client.runs if r["name"] == "tripradar.request")
    assert root["session_name"] == "tripradar-agents"
    assert all(r.get("parent_run_id") for r in client.runs if r is not root)


def test_disabled_never_constructs_client_and_missing_key_is_visible():
    def forbidden(**kwargs):
        raise AssertionError("Should not construct client")

    exporter = Exporter(
        Settings(_env_file=None, langsmith_tracing=False),
        lambda *a, **k: None,
        client_factory=forbidden,
    )
    assert exporter.status == "disabled"
    exporter = Exporter(
        Settings(_env_file=None, langsmith_tracing=True, langsmith_api_key=SecretStr("")),
        lambda *a, **k: None,
        client_factory=forbidden,
    )
    assert exporter.status == "missing_api_key"


def test_outage_does_not_raise_or_leak_and_queue_drains():
    reports = []

    def fail(*args):
        raise RuntimeError("secret=syntheticFailureToken")

    exporter = Exporter(
        settings(), lambda *a, **k: reports.append((a, k)), export=fail, client_factory=ClientDouble
    )
    exporter.submit({"request_id": uuid4().hex})
    exporter.close()
    assert exporter.status == "delivery_unconfirmed"
    assert "syntheticFailureToken" not in str(reports)
    assert reports


def test_trace_buffers_are_request_scoped_and_disabled_by_default(tmp_path):
    trace = Trace(tmp_path / "application.log")
    trace.begin("one", {"thread_id": "s"})
    trace.event("llm.input", request_id="one", content="sk-ant-syntheticSecret123456789")
    assert trace.requests == {}
    trace.close()
    assert "syntheticSecret" not in (tmp_path / "application.log").read_text()


def test_enabled_api_exports_clarification_without_waiting_for_worker(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from tripradar_agents.api import create_app

    client_double = ClientDouble()
    monkeypatch.setattr("langsmith.Client", lambda **kwargs: client_double)
    app = create_app(settings(database=tmp_path / "db.sqlite3"))
    with TestClient(app) as client:
        session = client.post("/sessions").json()
        headers = {"Authorization": session["capability"]}
        submitted = client.post(
            "/chat",
            headers=headers,
            json={
                "thread_id": session["thread_id"],
                "client_message_id": "trace-case",
                "message": "Plan a trip",
                "trip_fields": {},
            },
        )
        rid = submitted.json()["request_id"]
        for _ in range(100):
            response = client.get("/requests/" + rid, headers=headers).json()
            if response["status"] == "completed":
                break
            time.sleep(0.01)
        assert response["result"]["status"] == "needs_clarification"
    root = next(r for r in client_double.runs if r["name"] == "tripradar.request")
    assert str(root["id"]).replace("-", "") == rid
    assert root["outputs"]["status"] == "needs_clarification"
    assert session["capability"] not in json.dumps(client_double.runs, default=str)
    assert any(r["run_type"] == "llm" for r in client_double.runs)
