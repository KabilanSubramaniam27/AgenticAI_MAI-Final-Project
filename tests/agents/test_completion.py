import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from tripradar_agents.config import Settings
from tripradar_agents.evaluation import metrics
from tripradar_agents.grounding import verify
from tripradar_agents.ledger import calculate, reconcile, weather_days
from tripradar_agents.models import Activity, ChatRequest
from tripradar_agents.providers import Reader, amadeus_prices
from tripradar_agents.security import digest

TRIP = {
    "destination": "Lisbon",
    "start_date": "2026-10-10",
    "end_date": "2026-10-19",
    "budget": "2000",
    "currency": "USD",
    "origin": "JFK",
    "adults": 2,
    "rooms": 1,
}


def offer(category, amount, **extra):
    return {
        "id": category,
        "kind": "price",
        "category": category,
        "amount": amount,
        "trip": TRIP,
        "destination": "Lisbon",
        "environment": "fixture",
        "currency": "USD",
        "taxes_known": True,
        "fees_known": True,
        "price_basis": "whole_party_whole_stay",
        "retrieved_at": datetime.now(UTC).isoformat(),
        **extra,
    }


def test_ledger_whole_stay_and_explicit_allowances():
    rows = {c: offer(c, v) for c, v in (("flight_total", "600"), ("hotel_total", "900"))}
    allowances = [
        {
            "id": c,
            "category": c,
            "amount": a,
            "source": "user_form",
            "status": "accepted",
            "state_hash": digest(TRIP),
            "currency": "USD",
        }
        for c, a in (
            ("food", "200"),
            ("local_transport", "100"),
            ("activities", "100"),
            ("mandatory_fees", "0"),
        )
    ]
    result = calculate(TRIP, rows, list(rows), allowances)
    assert result["total"] == "1900.00"
    assert result["delta"] == "100.00"
    assert result["fits_budget"] is True
    assert result["verdict_basis"] == "test_data"
    assert calculate(TRIP, rows, list(rows))["total"] is None
    rows["second-hotel"] = {**rows["hotel_total"], "id": "second-hotel"}
    with pytest.raises(ValueError, match="Overlapping"):
        calculate(TRIP, rows, list(rows), allowances)
    allowances[0]["source"] = "model"
    with pytest.raises(ValueError, match="provenance"):
        calculate(TRIP, rows, ["flight_total", "hotel_total"], allowances)


def test_stale_foreign_and_unknown_tax_evidence():
    row = offer("hotel_total", "2200", taxes_known=False)
    result = calculate(TRIP, {row["id"]: row}, [row["id"]])
    assert result["verdict"] == "over" and result["total"] is None
    assert "unconfirmed_provider_fees" in result["missing"]
    row["retrieved_at"] = (datetime.now(UTC) - timedelta(minutes=16)).isoformat()
    with pytest.raises(ValueError, match="expired"):
        calculate(TRIP, {row["id"]: row}, [row["id"]])


def test_fx_direction_rounding_and_stale_rate():
    row = offer("hotel_total", "900.005", currency="EUR")

    def response(request):
        assert request.url.path == "/v2/rate/EUR/USD"
        return httpx.Response(
            200,
            json={
                "base": "EUR",
                "quote": "USD",
                "rate": 1.1,
                "date": datetime.now(UTC).date().isoformat(),
            },
        )

    reader = Reader(client=httpx.Client(transport=httpx.MockTransport(response)))
    try:
        result = calculate(TRIP, {row["id"]: row}, [row["id"]], reader=reader)
        assert result["known_subtotal"] == "990.01"
        assert result["fx_evidence"][0]["rate"] == "1.1"
    finally:
        reader.close()


def test_read_attempts_and_auth_failure_not_retried(monkeypatch):
    monkeypatch.setattr("tripradar_agents.providers.time.sleep", lambda _: None)
    attempts = []

    def response(request):
        attempts.append(request)
        return httpx.Response(503 if len(attempts) == 1 else 200, json={"ok": True})

    reader = Reader(client=httpx.Client(transport=httpx.MockTransport(response)))
    try:
        assert reader.request("GET", "https://example.invalid") == {"ok": True}
        assert reader.attempts == 2
    finally:
        reader.close()
    reader = Reader(
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    )
    try:
        with pytest.raises(ValueError, match="http_401"):
            reader.request("GET", "https://example.invalid")
        assert reader.attempts == 1
    finally:
        reader.close()


def test_amadeus_adapter_request_and_group_total():
    requests = []

    def response(request):
        requests.append(request)
        if request.url.path.endswith("token"):
            return httpx.Response(200, json={"access_token": "synthetic"})
        if request.url.path.endswith("flight-offers"):
            assert request.url.params["adults"] == "2"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "F1",
                            "price": {"total": "1200", "currency": "USD"},
                            "travelerPricings": [{}, {}],
                            "itineraries": [
                                {
                                    "segments": [
                                        {
                                            "departure": {
                                                "iataCode": "JFK",
                                                "at": "2026-10-10T01:00:00",
                                            },
                                            "arrival": {
                                                "iataCode": "LIS",
                                                "at": "2026-10-10T09:00:00",
                                            },
                                        }
                                    ]
                                },
                                {
                                    "segments": [
                                        {
                                            "departure": {
                                                "iataCode": "LIS",
                                                "at": "2026-10-19T10:00:00",
                                            },
                                            "arrival": {
                                                "iataCode": "JFK",
                                                "at": "2026-10-19T15:00:00",
                                            },
                                        }
                                    ]
                                },
                            ],
                        }
                    ]
                },
            )
        if request.url.path.endswith("by-city"):
            return httpx.Response(200, json={"data": [{"hotelId": "H1"}]})
        assert request.url.params["adults"] == "2"
        assert request.url.params["roomQuantity"] == "1"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "available": True,
                        "hotel": {"hotelId": "H1"},
                        "offers": [
                            {
                                "id": "H-OFFER",
                                "checkInDate": TRIP["start_date"],
                                "checkOutDate": TRIP["end_date"],
                                "guests": {"adults": 2},
                                "roomQuantity": "1",
                                "price": {"total": "900", "currency": "USD", "taxes": []},
                            }
                        ],
                    }
                ]
            },
        )

    reader = Reader(client=httpx.Client(transport=httpx.MockTransport(response)))
    try:
        settings = Settings(
            _env_file=None,
            amadeus_client_id=SecretStr("synthetic"),
            amadeus_client_secret=SecretStr("synthetic"),
        )
        rows = amadeus_prices(TRIP, settings, reader)
        assert [r["amount"] for r in rows] == ["1200", "900"]
        assert all(r["provider_environment"] == "test" for r in rows)
        assert reader.attempts == 4
        assert all(r.url.host == "test.api.amadeus.com" for r in requests)
    finally:
        reader.close()


def test_arrival_reconciliation_and_weather_exposure():
    activities = [
        Activity(date=day, claim="Walk", quote="Walk", evidence_id="G", exposure="outdoor")
        for day in ("2026-10-10", "2026-10-11", "2026-10-12", "2026-10-19")
    ]
    flight = offer(
        "flight_total", "600", arrival="2026-10-11T23:00:00", departure="2026-10-19T06:00:00"
    )
    accepted, result = reconcile(TRIP, activities, {"F": flight}, ["F"])
    assert [a.date.isoformat() for a in accepted] == ["2026-10-12"]
    assert result["removed_claims"] == 3
    forecast = {
        "kind": "weather",
        "daily": {"2026-10-12": 60},
        "retrieved_at": datetime.now(UTC).isoformat(),
    }
    days = weather_days(TRIP, accepted, {"W": forecast}, ["W"])
    assert days[2]["conflicts"][0]["conflict"] is True
    assert days[0]["weather"] == "unknown"
    accepted[0].exposure = "unknown"
    assert (
        weather_days(TRIP, accepted, {"W": forecast}, ["W"])[2]["conflicts"][0]["conflict"] is None
    )


def test_verifier_hash_mismatch_blocks_claim(monkeypatch):
    activity = Activity(date="2026-10-12", claim="Walk", quote="Walk", evidence_id="G")

    async def fake(*args, **kwargs):
        return {
            "results": [
                {
                    "claim_id": "0",
                    "claim_hash": "forged",
                    "source_hash": "forged",
                    "status": "supported",
                    "quote": "Walk",
                    "reason": "unsupported assertion",
                }
            ]
        }

    monkeypatch.setattr("tripradar_agents.grounding.run_agent", fake)

    class Trace:
        def event(self, *args, **kwargs):
            pass

    artifacts = {}
    assert (
        asyncio.run(
            verify([activity], TRIP, {"G": {"text": "Walk"}}, None, None, Trace(), "R", artifacts)
        )
        == []
    )
    assert artifacts["grounding_error"] == "ValueError"


def test_judge_metrics_abstention_and_hashes():
    labels = [
        {
            "label_status": "frozen",
            "response_id": str(i),
            "criterion_id": "grounding",
            "rubric_version": "v1",
            "reference_label": label,
            "severity": "critical",
            "response_sha256": "a",
            "evidence_sha256": "b",
        }
        for i, label in enumerate(["fail", "pass", "fail"])
    ]
    judgments = [
        {
            "judge_run_id": "run",
            "response_id": str(i),
            "criterion_id": "grounding",
            "rubric_version": "v1",
            "judge_label": label,
            "execution_status": "completed",
            "response_sha256": "a",
            "evidence_sha256": "b",
        }
        for i, label in enumerate(["fail", "fail", "inconclusive"])
    ]
    result = metrics(labels, judgments, "run")
    assert result["precision"] == 0.5 and result["recall"] == 1
    assert result["coverage"] == 2 / 3 and result["critical_misses"] == 1
    assert metrics([], [], "run")["f1"] is None
    judgments[0]["response_sha256"] = "changed"
    with pytest.raises(ValueError, match="snapshot"):
        metrics(labels, judgments, "run")


def test_allowances_cannot_carry_model_approval():
    with pytest.raises(ValueError):
        ChatRequest(
            thread_id="s",
            client_message_id="m",
            message="trip",
            allowances={"food": {"amount": 20, "approved": True}},
        )
    with pytest.raises(ValueError):
        ChatRequest(
            thread_id="s",
            client_message_id="m",
            message="trip",
            allowances={"food": Decimal("NaN")},
        )


def test_retrieval_group_capacity_and_empty_slots():
    from tripradar_agents.retrieval_evaluation import retrieval_metrics

    result = retrieval_metrics(["a", "a", "x"], {"landmark": ["a", "b"]}, ["a", "b"], witness=["a"])
    assert result["precision_at_k"] == 0.2
    assert result["evidence_group_recall_at_k"] == 1
    assert result["passage_recall_at_k"] == 0.5
    with pytest.raises(ValueError, match="witness"):
        retrieval_metrics(["a"], {"landmark": ["a"]}, ["a"], witness=["x"])
    assert retrieval_metrics([], {}, [])["correct_abstention"] is True


def test_capture_is_immutable_and_checks_snapshot(tmp_path):
    from tripradar_agents.evaluation import capture, read_csv, snapshot
    from tripradar_agents.store import Store

    store = Store(tmp_path / "app.sqlite3")
    session = store.session()
    payload = {
        "thread_id": session["thread_id"],
        "client_message_id": "m",
        "message": "Plan Lisbon",
        "trip_fields": TRIP,
    }
    rid, _ = store.admit(payload, session["capability"])
    store.finish(rid, {"answer": "Partial", "environment": "fixture"}, {"evidence": {}}, TRIP)
    root = tmp_path / "benchmark"
    folder = capture(store.path, rid, root, "TR-E2E-001", "lisbon-one")
    row = read_csv(root / "agent_responses.csv")[0]
    assert snapshot(root, row)[0]["answer"] == "Partial"
    assert read_csv(root / "human_reviews.csv") == []
    with pytest.raises(FileExistsError):
        capture(store.path, rid, root, "TR-E2E-001", "lisbon-one")
    (folder / "evidence.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="changed"):
        snapshot(root, row)


def test_tracking_queue_commit_restart_and_daily_cap(tmp_path, monkeypatch):
    from tripradar_agents.store import Store
    from tripradar_agents.tracking import claim

    # Synthetic acceptance is a unit-test precondition, never written to a live profile.
    store = Store(tmp_path / "app.sqlite3", judge_profile={"synthetic": True})
    monkeypatch.setattr("tripradar_agents.tracking.digest", lambda _: "0" * 64)
    session = store.session()
    for i in range(11):
        rid, _ = store.admit(
            {"thread_id": session["thread_id"], "client_message_id": str(i), "message": "trip"},
            session["capability"],
        )
        assert store.finish(rid, {"answer": "Plan"}, {}, TRIP)
    first = claim(store)
    assert first
    store.restart()
    with store.connect() as db:
        assert (
            db.execute("SELECT status FROM judge_jobs WHERE id=?", (first["id"],)).fetchone()[0]
            == "interrupted"
        )
        assert (
            db.execute("SELECT COUNT(*) FROM judge_jobs WHERE status='queued'").fetchone()[0] == 10
        )
    for _ in range(9):
        assert claim(store)
    assert claim(store) is None
    store.delete(session["thread_id"], session["capability"])
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM judge_jobs").fetchone()[0] == 0


def test_background_judge_cannot_enable_without_acceptance(tmp_path):
    from tripradar_agents.tracking import profile

    settings = Settings(_env_file=None, judge_tracking=False)
    assert profile(settings) is None
    settings.judge_tracking = True
    settings.judge_acceptance_path = tmp_path / "missing.json"
    with pytest.raises(FileNotFoundError):
        profile(settings)


def test_schema_recovery_is_bounded_and_revalidated(monkeypatch):
    from tripradar_agents.models import Selection
    from tripradar_agents.recovery import typed_call

    calls = []

    async def fake(role, *args):
        calls.append(role)
        return {"incorrect": True} if role != "repair" else {"evidence_ids": []}

    monkeypatch.setattr("tripradar_agents.recovery.run_agent", fake)

    class Trace:
        def event(self, *args, **kwargs):
            pass

    artifacts = {}
    result = asyncio.run(
        typed_call("price_watcher", {}, Selection, None, None, Trace(), "R", artifacts)
    )
    assert result.evidence_ids == [] and calls == ["price_watcher", "repair"]
    assert artifacts["security_incidents"][0]["learning_status"] == "pending_human_review"
    with pytest.raises(ValueError, match="exhausted"):
        asyncio.run(typed_call("price_watcher", {}, Selection, None, None, Trace(), "R", artifacts))


def test_real_human_review_capture_requires_two_reviewers(tmp_path):
    import json

    from tripradar_agents.evaluation import adjudicate, capture, read_csv, record_review
    from tripradar_agents.store import Store

    store = Store(tmp_path / "app.sqlite3")
    session = store.session()
    rid, _ = store.admit(
        {"thread_id": session["thread_id"], "client_message_id": "m", "message": "trip"},
        session["capability"],
    )
    store.finish(rid, {"answer": "Partial"}, {"evidence": {}}, TRIP)
    root = tmp_path / "review"
    capture(store.path, rid, root, "TR-E2E-001", "synthetic-unit-test-family")
    response_id = rid + "-orchestrator"
    version = json.loads((root / "rubric_v1.json").read_text())["version"]
    first = record_review(
        root,
        response_id,
        "grounding",
        "synthetic-reviewer-A",
        "inconclusive",
        "Unit test review only",
        version,
    )
    with pytest.raises(ValueError, match="Two independent"):
        adjudicate(
            root,
            first,
            "inconclusive",
            "synthetic-adjudicator",
            "Unit test only",
            "calibration",
            "minor",
        )
    second = record_review(
        root,
        response_id,
        "grounding",
        "synthetic-reviewer-B",
        "inconclusive",
        "Unit test review only",
        version,
    )
    adjudicate(
        root,
        first + ";" + second,
        "inconclusive",
        "synthetic-adjudicator",
        "Unit test only",
        "calibration",
        "minor",
    )
    assert len(read_csv(root / "adjudicated_labels.csv")) == 1
    with pytest.raises(ValueError, match="Duplicate"):
        adjudicate(
            root,
            first + ";" + second,
            "inconclusive",
            "synthetic-adjudicator",
            "Unit test only",
            "calibration",
            "minor",
        )


def test_invalid_tracking_profile_does_not_break_planning_api(tmp_path):
    from fastapi.testclient import TestClient

    from tripradar_agents.api import create_app

    settings = Settings(
        _env_file=None,
        mode="fixture",
        database=tmp_path / "app.sqlite3",
        judge_tracking=True,
        judge_acceptance_path=tmp_path / "absent.json",
    )
    with TestClient(create_app(settings)) as client:
        result = client.get("/ready")
        assert result.status_code == 200
        assert result.json()["background_judge"] == "blocked_invalid_acceptance"


def test_malformed_json_uses_only_one_repair(monkeypatch):
    import json

    from tripradar_agents.models import Selection
    from tripradar_agents.recovery import typed_call

    calls = []

    async def fake(role, *args, **kwargs):
        calls.append(role)
        if role != "repair":
            raise json.JSONDecodeError("bad JSON", '{"evidence_ids": [}', 18)
        return {"evidence_ids": []}

    monkeypatch.setattr("tripradar_agents.recovery.run_agent", fake)

    class Trace:
        def event(self, *args, **kwargs):
            pass

    result = asyncio.run(typed_call("price_watcher", {}, Selection, None, None, Trace(), "R", {}))
    assert result.evidence_ids == [] and calls == ["price_watcher", "repair"]
