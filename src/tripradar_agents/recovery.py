"""Bounded policy → guardrail → detection → response → review-candidate loop."""

import json
from uuid import uuid4

from pydantic import ValidationError

from .llm import run_agent
from .security import GuardrailError, digest


async def typed_call(role, context, schema, settings, budget, trace, rid, artifacts, **kwargs):
    try:
        raw = await run_agent(role, context, settings, budget, trace, rid, artifacts, **kwargs)
    except json.JSONDecodeError as exc:
        raw = {"malformed_json": exc.doc}
    try:
        return schema.model_validate(raw)
    except ValidationError as exc:
        incident = {
            "id": uuid4().hex,
            "policy": "structured-output-v1",
            "agent": role,
            "detection": "invalid_schema",
            "response_hash": digest(raw),
            "issues": [
                {"location": list(e["loc"]), "type": e["type"]}
                for e in exc.errors(include_input=False, include_url=False)
            ],
            "learning_status": "pending_human_review",
        }
        artifacts.setdefault("security_incidents", []).append(incident)
        trace.event("guardrail.decision", request_id=rid, decision="repair", **incident)
        counters = artifacts.setdefault("recovery", {"total": 0, "schema": 0, "grounding": 0})
        if counters["total"] >= 2 or counters["schema"] >= 1:
            raise GuardrailError("Schema recovery exhausted") from exc
        counters["total"] += 1
        counters["schema"] += 1
        repaired = await run_agent(
            "repair",
            {
                "stage": "repair",
                "original_role": role,
                "schema": schema.model_json_schema(),
                "candidate": raw,
                "issues": incident["issues"],
                "context": context,
            },
            settings,
            budget,
            trace,
            rid,
            artifacts,
        )
        # No recursive repair. Downstream source/scope/semantic checks still run.
        return schema.model_validate(repaired)
