"""Opt-in post-response evaluation. Human-calibrated acceptance is mandatory."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .config import ROOT
from .evaluation import Judgment, sha
from .llm import run_agent
from .models import Strict
from .security import Budget, digest, redact


class CriterionJudgment(Judgment):
    criterion_id: str


class JudgeBatch(Strict):
    judgments: list[CriterionJudgment] = Field(max_length=20)


def profile(settings):
    if not settings.judge_tracking:
        return None
    path = settings.judge_acceptance_path
    data = json.loads(path.read_text())
    if (
        data.get("accepted") is not True
        or data.get("judge_model") != settings.model
        or data.get("judge_prompt_hash") != digest((ROOT / "config/prompts/judge.md").read_text())
        or sha(data["rubric_path"]) != data["rubric_sha256"]
    ):
        raise ValueError("Background judge acceptance is missing or stale")
    if settings.mode != "live":
        raise ValueError("Background judge requires live OpenAI configuration")
    return data


def schedule(db, rid, result, artifacts, acceptance):
    if not acceptance or int(digest(rid)[:8], 16) / 0x100000000 >= 0.10:
        return
    body = {
        "response": result,
        "query": artifacts.get("request_query", ""),
        "evidence": artifacts.get("evidence", {}),
        "specialists": artifacts.get("specialists", {}),
        "profile": acceptance,
    }
    db.execute(
        "INSERT OR IGNORE INTO judge_jobs(id,request_id,status,created,payload) VALUES(?,?,'queued',?,?)",
        (uuid4().hex, rid, datetime.now(UTC).isoformat(), json.dumps(body)),
    )


def claim(store):
    today = datetime.now(UTC).date().isoformat()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        used = db.execute(
            "SELECT COALESCE(SUM(reserved),0) FROM judge_jobs WHERE charged_day=?", (today,)
        ).fetchone()[0]
        if used + 1 > 10:
            return None
        row = db.execute(
            "SELECT * FROM judge_jobs WHERE status='queued' ORDER BY created LIMIT 1"
        ).fetchone()
        if not row:
            return None
        db.execute(
            "UPDATE judge_jobs SET status='running',charged_day=?,reserved=1 WHERE id=? AND status='queued'",
            (today, row["id"]),
        )
        return dict(row)


async def work(store, settings, trace):
    current_profile = profile(settings)
    while True:
        job = claim(store)
        if not job:
            await asyncio.sleep(1)
            continue
        artifacts, outputs = {}, {}
        try:
            payload = json.loads(job["payload"])
            if digest(payload["profile"]) != digest(current_profile):
                raise ValueError("Queued judge configuration is stale")
            rubric = json.loads(Path(current_profile["rubric_path"]).read_text())
            budget = Budget(
                settings.model_copy(update={"request_cost_cap": 1, "max_model_calls": 12})
            )
            responses = {"orchestrator": payload["response"], **payload["specialists"]}
            # Sampled monitoring estimates are not human reference labels or new reliability scores.
            for role, response in responses.items():
                if not budget.can_reserve(1, 16000, 1000, seconds=1):
                    outputs[role] = {"label": "inconclusive", "reason": "job_budget_exhausted"}
                    continue
                batch = JudgeBatch.model_validate(
                    await run_agent(
                        "judge",
                        {
                            "stage": "judge",
                            "agent": role,
                            "query": payload.get("query", ""),
                            "response": response,
                            "criteria": rubric["criteria"],
                            "evidence": payload["evidence"],
                        },
                        settings,
                        budget,
                        trace,
                        job["id"],
                        artifacts,
                    )
                )
                if len(batch.judgments) != len(rubric["criteria"]) or {
                    j.criterion_id for j in batch.judgments
                } != set(rubric["criteria"]):
                    raise ValueError("Incomplete judge batch")
                for answer in batch.judgments:
                    if not set(answer.evidence_ids) <= set(payload["evidence"]):
                        raise ValueError("Unknown judge evidence")
                    outputs[role + ":" + answer.criterion_id] = answer.model_dump()
            status = "completed"
        except asyncio.CancelledError:
            status = "interrupted"
            raise
        except Exception as exc:
            status = "error"
            outputs["error"] = type(exc).__name__
        finally:
            with store.connect() as db:
                db.execute(
                    "UPDATE judge_jobs SET status=?,result=? WHERE id=? AND status='running'",
                    (
                        status,
                        json.dumps(redact({"estimates": outputs, "artifacts": artifacts})),
                        job["id"],
                    ),
                )
            trace.event("judge.end", request_id=job["request_id"], job_id=job["id"], status=status)
