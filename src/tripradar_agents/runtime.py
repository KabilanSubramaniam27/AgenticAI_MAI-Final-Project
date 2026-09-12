import asyncio
import json
from decimal import Decimal

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from .grounding import verify
from .ledger import calculate, fresh, reconcile, weather_days
from .mcp_client import call_mcp
from .models import Itinerary, PlanningDone, Proposal, Selection
from .recovery import typed_call
from .security import Budget, GuardrailError, checked_text, digest, normalize, validate_activities


class Runtime:
    def __init__(self, settings, trace):
        self.settings, self.trace = settings, trace
        from pathlib import Path

        self.code_version = digest(
            {p.name: p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))}
        )

    async def run(self, rid, payload, history, prior, artifacts):
        budget = Budget(self.settings)
        async with asyncio.timeout(self.settings.deadline_seconds):
            try:
                return await self._run(rid, payload, history, prior, artifacts, budget)
            except ValidationError as exc:
                # Preserve useful diagnostics without input values or arbitrary error messages.
                issues = [
                    {"location": [str(x) for x in e["loc"]], "type": e["type"]}
                    for e in exc.errors(include_input=False, include_url=False)
                ]
                artifacts["validation_failure"] = {
                    "schema": exc.title,
                    "stage": artifacts.get("stage"),
                    "issues": issues,
                }
                self.trace.event(
                    "validation.failure", request_id=rid, **artifacts["validation_failure"]
                )
                raise

    async def _run(self, rid, payload, history, prior, artifacts, budget):
        message = checked_text(payload["message"])
        artifacts["request_query"] = message
        artifacts["configuration"] = {
            "provider": self.settings.provider,
            "code_version": self.code_version,
            "model": self.settings.model,
            "specialist_model": self.settings.specialist_model,
            "mode": self.settings.mode,
            "input_usd_per_million": self.settings.input_usd_per_million,
            "output_usd_per_million": self.settings.output_usd_per_million,
            "collection": self.settings.chroma_collection,
            "backend": self.settings.chroma_backend,
        }
        # Trim whole exchanges. Full accepted constraints remain separate from chat history.
        while history and len(str(history).encode()) > 3000:
            history = history[2:]
        artifacts["stage"] = "request_extraction"
        proposal = await typed_call(
            "orchestrator",
            {
                "stage": "extract",
                "message": message,
                "history": history,
                "prior_trip": prior,
                "structured_fields": payload["trip_fields"],
            },
            Proposal,
            self.settings,
            budget,
            self.trace,
            rid,
            artifacts,
        )
        trip, questions = normalize(message, payload["trip_fields"], proposal.facts, prior)
        artifacts["extraction"] = proposal.model_dump()
        artifacts["validated_trip"] = trip
        if questions:
            return {
                "status": "needs_clarification",
                "answer": " ".join(questions),
                "environment": self.settings.mode,
                "trip": trip,
            }, trip
        results, evidence = {}, {}
        allowances = [
            {
                "id": digest([rid, category, amount]),
                "category": category,
                "amount": str(amount),
                "currency": trip["currency"],
                "state_hash": digest(trip),
                "status": "accepted",
                "source": "user_form",
                "request_id": rid,
            }
            for category, amount in payload.get("allowances", {}).items()
        ]
        if not payload.get("clear_allowances"):
            replaced = {a["category"] for a in allowances}
            allowances.extend(
                a
                for a in payload.get("_prior_allowances", [])
                if a.get("state_hash") == digest(trip) and a["category"] not in replaced
            )
        artifacts["allowances"] = allowances
        common = {"trip": trip, "mode": self.settings.mode, "allowances": allowances}
        order = ["itinerary_builder", "price_watcher", "weather_risk"]

        async def specialist(role):
            if role in results or order[len(results)] != role:
                raise GuardrailError("Duplicate or out-of-order specialist delegation")
            domain, arguments = {
                "itinerary_builder": (
                    "destination",
                    {"query": "Things to see and do " + trip["destination"]},
                ),
                "price_watcher": ("pricing", {}),
                "weather_risk": ("weather", {}),
            }[role]
            self.trace.event("agent.start", request_id=rid, agent=role)
            try:
                rows = await call_mcp(role, domain, arguments, common, budget, self.trace, rid)
            except Exception:
                # A tool fault is visible, never silently replaced with fixture data.
                rows = []
                artifacts.setdefault("limitations", []).append(domain + " evidence unavailable")
            for row in rows:
                if (
                    row.get("destination") != trip["destination"]
                    or row.get("environment") != self.settings.mode
                ):
                    raise GuardrailError("Cross-scope evidence")
                evidence[row["id"]] = row
            # Keep whole evidence records within context; omitted records remain in the scoped repository.
            model_rows = []
            for row in rows:
                if len(json.dumps(model_rows + [row]).encode()) <= 10000:
                    model_rows.append(row)
            if len(model_rows) != len(rows):
                self.trace.event(
                    "context.trim",
                    request_id=rid,
                    agent=role,
                    retained=len(model_rows),
                    available=len(rows),
                )
            artifacts["stage"] = role
            result = await typed_call(
                role,
                {
                    "stage": "specialist",
                    "trip": trip,
                    "request": message,
                    "history": history,
                    "evidence": model_rows,
                    "itinerary": results.get("itinerary_builder", {}),
                    "selected_offers": results.get("price_watcher", {}),
                },
                Itinerary if role == "itinerary_builder" else Selection,
                self.settings,
                budget,
                self.trace,
                rid,
                artifacts,
            )
            if role == "itinerary_builder":
                # Store only deterministic-valid candidates; semantic verification follows before delivery.
                result = {
                    "activities": [
                        a.model_dump(mode="json")
                        for a in validate_activities(result.activities, trip, evidence)
                    ]
                }
            else:
                selection = result
                allowed = {r["id"] for r in rows if r["kind"] in ("price", "weather")}
                if not set(selection.evidence_ids) <= allowed:
                    raise GuardrailError("Specialist selected unknown evidence")
                result = selection.model_dump()
            results[role] = result
            self.trace.event("agent.end", request_id=rid, agent=role)
            return {
                "messages": [
                    AIMessage(content="Specialist completed; application retained validated data.")
                ]
            }

        subagents = []
        for role in order:

            async def invoke(state, role=role):
                return await specialist(role)

            subagents.append(
                {
                    "name": role,
                    "description": "Run " + role + " on the validated trip.",
                    "runnable": RunnableLambda(invoke),
                }
            )
        artifacts["stage"] = "orchestrator_planning"
        await typed_call(
            "orchestrator",
            {"stage": "plan", "trip": trip, "request": message, "history": history},
            PlanningDone,
            self.settings,
            budget,
            self.trace,
            rid,
            artifacts,
            subagents=subagents,
        )
        if set(results) != set(order):
            raise GuardrailError("Required specialist results missing")
        artifacts["evidence"] = evidence
        artifacts["specialists"] = results
        candidates = Itinerary.model_validate(results["itinerary_builder"]).activities
        selected_ids = results["price_watcher"]["evidence_ids"]
        selected_flights = [
            evidence[i] for i in selected_ids if evidence[i].get("category") == "flight_total"
        ]
        selected_hotels = [
            evidence[i] for i in selected_ids if evidence[i].get("category") == "hotel_total"
        ]
        if (
            selected_flights
            and selected_hotels
            and selected_hotels[0].get("check_in") != selected_flights[0]["arrival"][:10]
        ):
            # One bounded hotel repricing pass, preserving the user's original flight dates.
            dates = {
                "check_in": selected_flights[0]["arrival"][:10],
                "check_out": selected_flights[0]["departure"][:10],
            }
            if budget.can_reserve(1, 16000, 1000) and budget.reads + 4 <= self.settings.max_reads:
                try:
                    revised = await call_mcp(
                        "price_watcher",
                        "pricing",
                        {},
                        {**common, "hotel_dates": dates},
                        budget,
                        self.trace,
                        rid,
                    )
                    hotels = [
                        r
                        for r in revised
                        if r.get("category") == "hotel_total"
                        and r.get("kind") == "price"
                        and r.get("trip") == trip
                        and r.get("environment") == self.settings.mode
                    ]
                    evidence.update({r["id"]: r for r in hotels})
                    choice = await typed_call(
                        "price_watcher",
                        {"stage": "specialist", "trip": trip, "evidence": hotels},
                        Selection,
                        self.settings,
                        budget,
                        self.trace,
                        rid,
                        artifacts,
                    )
                    if len(choice.evidence_ids) != 1 or choice.evidence_ids[0] not in {
                        r["id"] for r in hotels
                    }:
                        raise GuardrailError("No eligible repriced hotel selected")
                    selected_ids = [r["id"] for r in selected_flights] + choice.evidence_ids
                    results["price_watcher"]["evidence_ids"] = selected_ids
                    artifacts["hotel_repricing"] = {
                        "passes": 1,
                        "dates": dates,
                        "selected_ids": selected_ids,
                    }
                except Exception as exc:
                    artifacts.setdefault("limitations", []).append(
                        "Hotel repricing unavailable: " + type(exc).__name__
                    )
                    selected_ids = [r["id"] for r in selected_flights]
                    results["price_watcher"]["evidence_ids"] = selected_ids
            else:
                selected_ids = [r["id"] for r in selected_flights]
                results["price_watcher"]["evidence_ids"] = selected_ids
                artifacts.setdefault("limitations", []).append(
                    "Hotel quote invalidated by arrival; repricing budget exhausted"
                )
        candidates, reconciliation = reconcile(trip, candidates, evidence, selected_ids)
        artifacts["reconciliation"] = reconciliation
        artifacts["stage"] = "grounding_verifier"
        accepted = await verify(
            candidates, trip, evidence, self.settings, budget, self.trace, rid, artifacts
        )
        # One revision episode may repair rejected claims or replace a rain-conflicting activity.
        initial_days = weather_days(
            trip, accepted, evidence, results["weather_risk"]["evidence_ids"]
        )
        rejected = len(accepted) < len(candidates)
        rainy = any(any(c["conflict"] for c in day["conflicts"]) for day in initial_days)
        counters = artifacts.setdefault("recovery", {"total": 0, "schema": 0, "grounding": 0})
        if (rejected or rainy) and budget.can_reserve(2, 28000, 7000) and len(candidates) <= 6:
            if not rejected or (counters["total"] < 2 and counters["grounding"] < 1):
                if rejected:
                    counters["total"] += 1
                    counters["grounding"] += 1
                artifacts["itinerary_revision"] = {
                    "passes": 1,
                    "reason": "grounding" if rejected else "rain_conflict",
                }
                trace_reason = artifacts["itinerary_revision"]["reason"]
                self.trace.event(
                    "security.response" if rejected else "agent.revision",
                    request_id=rid,
                    agent="itinerary_builder",
                    reason=trace_reason,
                )
                try:
                    revision = await typed_call(
                        "itinerary_builder",
                        {
                            "stage": "specialist",
                            "trip": trip,
                            "evidence": [r for r in evidence.values() if r["kind"] == "guide"],
                            "itinerary": [a.model_dump(mode="json") for a in accepted],
                            "weather_days": initial_days,
                            "reconciliation": reconciliation,
                            "revision": "Replace unsupported claims and outdoor rain conflicts only with evidenced alternatives",
                        },
                        Itinerary,
                        self.settings,
                        budget,
                        self.trace,
                        rid,
                        artifacts,
                    )
                    revised = validate_activities(revision.activities, trip, evidence)
                    revised, reconciliation = reconcile(trip, revised, evidence, selected_ids)
                    checked = await verify(
                        revised, trip, evidence, self.settings, budget, self.trace, rid, artifacts
                    )
                    if checked:
                        accepted = checked
                except Exception as exc:
                    artifacts.setdefault("limitations", []).append(
                        "Itinerary revision unavailable: " + type(exc).__name__
                    )
        try:
            budget_result = await call_mcp(
                "orchestrator",
                "currency",
                {"evidence_ids": results["price_watcher"]["evidence_ids"]},
                {**common, "evidence": evidence},
                budget,
                self.trace,
                rid,
            )
        except Exception as exc:
            artifacts.setdefault("limitations", []).append(
                "Budget evidence unavailable: " + type(exc).__name__
            )
            budget_result = calculate(trip, {}, [], allowances)
        if budget_result["verdict"] == "over" and budget.reads < self.settings.max_reads:
            current_hotels = [
                evidence[i] for i in selected_ids if evidence[i].get("category") == "hotel_total"
            ]
            if current_hotels and not artifacts.get("hotel_repricing"):
                current = current_hotels[0]
                alternatives = [
                    r
                    for r in evidence.values()
                    if r.get("kind") == "price"
                    and r.get("category") == "hotel_total"
                    and r.get("trip") == trip
                    and r.get("currency") == current["currency"]
                    and fresh(r)
                    and r.get("check_in") == current.get("check_in")
                    and r.get("check_out") == current.get("check_out")
                    and Decimal(r["amount"]) < Decimal(current["amount"])
                ]
                if alternatives:
                    alternative = min(alternatives, key=lambda r: Decimal(r["amount"]))
                    new_ids = [i for i in selected_ids if i != current["id"]] + [alternative["id"]]
                    revised, check = reconcile(trip, accepted, evidence, new_ids)
                    try:
                        revised_budget = await call_mcp(
                            "orchestrator",
                            "currency",
                            {"evidence_ids": new_ids},
                            {**common, "evidence": evidence},
                            budget,
                            self.trace,
                            rid,
                        )
                        accepted, reconciliation, budget_result, selected_ids = (
                            revised,
                            check,
                            revised_budget,
                            new_ids,
                        )
                        results["price_watcher"]["evidence_ids"] = new_ids
                        artifacts["hotel_alternative"] = {
                            "passes": 1,
                            "previous": current["id"],
                            "selected": alternative["id"],
                        }
                    except Exception as exc:
                        artifacts.setdefault("limitations", []).append(
                            "Hotel alternative could not be validated: " + type(exc).__name__
                        )
        days = weather_days(trip, accepted, evidence, results["weather_risk"]["evidence_ids"])
        limitations = list(reconciliation["limitations"])
        if any(
            not day["activities"] and day["date"] not in reconciliation["travel_days"]
            for day in days
        ):
            limitations.append(
                "Some dates have no supported activity; more relevant guide evidence is needed"
            )
        if any(day["weather"] == "unknown" for day in days):
            limitations.append("Weather is unknown outside actual forecast coverage")
        if any(any(c["conflict"] for c in day["conflicts"]) for day in days):
            limitations.append(
                "Rain conflicts remain; indoor alternatives require supported guide evidence"
            )
        limitations.append("Rain risk is a planning heuristic, not a safety guarantee")
        limitations.extend(artifacts.get("limitations", []))
        complete = (
            reconciliation.get("compatible", False)
            and budget_result["total"] is not None
            and all(
                day["activities"] or day["date"] in reconciliation["travel_days"] for day in days
            )
            and all(day["weather"] != "unknown" for day in days)
            and all(c["conflict"] is False for day in days for c in day["conflicts"])
        )
        verdict_text = budget_result["verdict"]
        if verdict_text == "fits" and allowances:
            verdict_text = "conditionally fits using your accepted spending allowances"
        if budget_result["verdict_basis"] == "test_data":
            verdict_text += " (test/fixture prices, not a live affordability check)"
        response = {
            "status": "complete" if complete else "partial",
            "environment": self.settings.mode,
            "answer": ("Itinerary prepared. " if complete else "Provisional itinerary prepared. ")
            + "Budget: "
            + verdict_text
            + ". See day coverage and limitations below.",
            "trip": trip,
            "reconciliation": reconciliation,
            "days": days,
            "budget": budget_result,
            "evidence": list(evidence.values()),
            "limitations": limitations,
        }
        artifacts["reconciliation"] = reconciliation
        artifacts["response_hash"] = digest(response)
        artifacts["usage"] = {
            "model_attempts": budget.calls,
            "reads": budget.reads,
            "reserved_cost": budget.reserved_cost,
        }
        return response, trip
