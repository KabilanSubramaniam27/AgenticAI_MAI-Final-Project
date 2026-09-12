"""Claim/source binding and fail-closed runtime semantic verification."""

from .llm import run_agent
from .models import GroundingResult
from .security import digest


async def verify_batch(candidates, trip, evidence, settings, budget, trace, rid, artifacts):
    if not candidates:
        return []
    claims = [
        {
            "claim_id": str(i),
            "claim_hash": digest(a.model_dump(mode="json")),
            "source_hash": digest(evidence[a.evidence_id]),
            "activity": a.model_dump(mode="json"),
        }
        for i, a in enumerate(candidates)
    ]
    sources = {a.evidence_id: evidence[a.evidence_id] for a in candidates}
    try:
        result = GroundingResult.model_validate(
            await run_agent(
                "grounding_verifier",
                {"stage": "verify", "trip": trip, "claims": claims, "evidence": sources},
                settings,
                budget,
                trace,
                rid,
                artifacts,
            )
        )
        expected = {c["claim_id"]: c for c in claims}
        if len(result.results) != len(expected) or {r.claim_id for r in result.results} != set(
            expected
        ):
            raise ValueError("Incomplete or duplicate verification")
        accepted = []
        for row in result.results:
            claim = expected[row.claim_id]
            if row.claim_hash != claim["claim_hash"] or row.source_hash != claim["source_hash"]:
                raise ValueError("Verification hash mismatch")
            source = sources[claim["activity"]["evidence_id"]]
            if row.status == "supported":
                if not row.quote or row.quote not in source["text"]:
                    raise ValueError("Unbound support span")
                accepted.append(candidates[int(row.claim_id)])
        artifacts["grounding"] = result.model_dump()
        return accepted
    except Exception as exc:
        artifacts["grounding_error"] = type(exc).__name__
        trace.event(
            "guardrail.decision",
            request_id=rid,
            policy="claim-support-v1",
            decision="block_unverified_claims",
            error=type(exc).__name__,
        )
        return []


async def verify(candidates, trip, evidence, settings, budget, trace, rid, artifacts):
    accepted, batches = [], []
    for offset in range(0, len(candidates), 6):
        batch_artifacts = {}
        accepted.extend(
            await verify_batch(
                candidates[offset : offset + 6],
                trip,
                evidence,
                settings,
                budget,
                trace,
                rid,
                batch_artifacts,
            )
        )
        artifacts.setdefault("model_calls", []).extend(batch_artifacts.pop("model_calls", []))
        batches.append(batch_artifacts)
        if "grounding_error" in batch_artifacts:
            artifacts["grounding_error"] = batch_artifacts["grounding_error"]
    artifacts["grounding_batches"] = batches
    return accepted
