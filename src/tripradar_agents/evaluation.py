"""Offline EDD capture and judge calibration. No writes to the destination collection."""

import argparse
import asyncio
import csv
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import Field

from .config import ROOT, Settings
from .llm import run_agent
from .models import Strict
from .observability import Trace
from .security import Budget, digest, redact
from .store import Store


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def write_json(path, data):
    # Exclusive creation keeps captured responses immutable.
    with Path(path).open("x") as file:
        json.dump(redact(data), file, indent=2, default=str)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def append_csv(path, template, values):
    path = Path(path)
    fields = read_csv_header(ROOT / "evals/review_templates" / template)
    exists = path.exists()
    with path.open("a", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({key: redact(values.get(key, "")) for key in fields})


def read_csv_header(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as file:
        return next(csv.reader(file))


def capture(
    database, request_id, destination, case_id, family_id, repetition=1, dataset_version=None
):
    """Explicit local operator export; API tokens/secrets excluded, never invents a review."""
    store = Store(Path(database))
    with store.connect() as db:
        row = db.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
    if not row or row["status"] not in {"completed", "failed", "interrupted"}:
        raise ValueError("A terminal request is required")
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    folder = root / request_id
    folder.mkdir()  # Cannot replace a baseline by rerunning export.
    artifacts = json.loads(row["artifacts"] or "{}")
    payload = json.loads(row["payload"])
    evidence = artifacts.get("evidence", {})
    write_json(folder / "evidence.json", evidence)
    write_json(
        folder / "context.json",
        {
            "case_id": case_id,
            "scenario_family_id": family_id,
            "query": payload["message"],
            "trip": artifacts.get("validated_trip"),
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    outputs = {
        "orchestrator": json.loads(row["result"] or "{}"),
        **artifacts.get("specialists", {}),
    }
    code_hash = digest(
        {p.name: sha(p) for p in sorted((ROOT / "src/tripradar_agents").glob("*.py"))}
    )
    for agent, response in outputs.items():
        calls = [c for c in artifacts.get("model_calls", []) if c.get("agent") == agent]
        usages = [u for c in calls for u in c.get("usage", []) if u]
        latest = calls[-1] if calls else {}
        config = artifacts.get("configuration", {})
        estimated_cost = (
            sum(
                u.get("input_tokens", 0) * config.get("input_usd_per_million", 0)
                + u.get("output_tokens", 0) * config.get("output_usd_per_million", 0)
                for u in usages
            )
            / 1000000
            if usages and config
            else None
        )
        target = folder / f"{agent}.json"
        write_json(target, response)
        append_csv(
            root / "agent_responses.csv",
            "agent_responses.csv",
            {
                "response_id": request_id + "-" + agent,
                "run_id": request_id,
                "case_id": case_id,
                "agent": agent,
                "thread_id": row["session"],
                "repetition": repetition,
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "query": payload["message"],
                "context_ref": str((folder / "context.json").relative_to(root)),
                "evidence_ref": str((folder / "evidence.json").relative_to(root)),
                "evidence_sha256": sha(folder / "evidence.json"),
                "response_payload_ref": str(target.relative_to(root)),
                "response_sha256": sha(target),
                "response_status": row["status"],
                "backend_mode": response.get(
                    "environment", outputs["orchestrator"].get("environment", "")
                ),
                "agent_model": latest.get("model", "unavailable"),
                "code_version": config.get("code_version", code_hash),
                "dataset_version": dataset_version
                or sha(ROOT / "evals/Golden_Dataset_V1_manifest.json"),
                "latency_ms": sum(c.get("latency_ms", 0) for c in calls),
                "input_tokens": sum(u.get("input_tokens", 0) for u in usages) if usages else "",
                "output_tokens": sum(u.get("output_tokens", 0) for u in usages) if usages else "",
                "cost_basis": "estimated" if estimated_cost is not None else "unavailable",
                "cost_amount": estimated_cost if estimated_cost is not None else "",
                "cost_currency": "USD",
                "as_of_utc": datetime.fromtimestamp(row["created"], UTC).isoformat(),
                "agent_prompt_version": latest.get("prompt_hash", "unavailable"),
            },
        )
    write_json(folder / "artifacts.json", artifacts)
    import shutil

    for template in (
        "human_reviews.csv",
        "adjudicated_labels.csv",
        "judge_evaluations.csv",
        "item_labels.csv",
        "metric_summaries.csv",
        "rubric_v1.json",
    ):
        if not (root / template).exists():
            shutil.copyfile(ROOT / "evals/review_templates" / template, root / template)
    write_json(folder / "manifest.json", {p.name: sha(p) for p in sorted(folder.glob("*.json"))})
    return folder


def snapshot(root, row):
    """Check paths and content hashes before scoring; no model-controlled URLs or traversal."""
    values = []
    root = Path(root).resolve()
    for ref, hash_key in (
        ("response_payload_ref", "response_sha256"),
        ("evidence_ref", "evidence_sha256"),
    ):
        path = (root / row[ref]).resolve()
        if not path.is_relative_to(root) or sha(path) != row[hash_key]:
            raise ValueError("Evidence or response snapshot changed")
        values.append(json.loads(path.read_text()))
    return values


def validate_labels(root, labels):
    responses = {r["response_id"]: r for r in read_csv(Path(root) / "agent_responses.csv")}
    reviews = {r["review_id"]: r for r in read_csv(Path(root) / "human_reviews.csv")}
    seen, family_splits = set(), {}
    for label in labels:
        if label["label_status"] != "frozen":
            raise ValueError("Reference labels must be frozen by a human")
        row = responses[label["response_id"]]
        snapshot(root, row)
        if any(label[k] != row[k] for k in ("response_sha256", "evidence_sha256")):
            raise ValueError("Reference hash mismatch")
        key = (label["response_id"], label["criterion_id"], label["rubric_version"])
        if key in seen:
            raise ValueError("Duplicate active reference label")
        seen.add(key)
        family = label["scenario_family_id"]
        if not family or (family in family_splits and family_splits[family] != label["split"]):
            raise ValueError("Scenario family leaks across evaluation splits")
        family_splits[family] = label["split"]
        source = [reviews[r] for r in label["source_review_ids"].split(";") if r]
        if len({r["reviewer_id"] for r in source}) < 2:
            raise ValueError("Two independent human reviewers are required")
        for review in source:
            if (
                review["review_status"] != "submitted"
                or review["response_id"] != label["response_id"]
                or review["criterion_id"] != label["criterion_id"]
                or review["rubric_version"] != label["rubric_version"]
                or any(review[k] != label[k] for k in ("response_sha256", "evidence_sha256"))
            ):
                raise ValueError("Inapplicable human review")
        if not label["adjudicator_id"] or not label["rationale"]:
            raise ValueError("Human adjudication metadata is required")
    return responses


class Judgment(Strict):
    label: str = Field(pattern="^(pass|fail|inconclusive|not_applicable)$")
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


async def judge(root, rubric_path, split, settings):
    root = Path(root)
    labels = read_csv(root / "adjudicated_labels.csv")
    responses = validate_labels(root, labels)
    rubric = json.loads(Path(rubric_path).read_text())
    selected = [label for label in labels if label["split"] == split]
    if not selected:
        raise ValueError("No reviewed labels for this split")
    if settings.mode != "live" or settings.readiness():
        raise ValueError("Judge requires configured live OpenAI; no scripted judge fallback")
    if rubric.get("status") != "frozen":
        raise ValueError("Freeze the human-reviewed rubric before judging")
    rid = uuid4().hex
    trace = Trace(root / "judge-application.log", settings)
    try:
        for label in selected:
            row = responses[label["response_id"]]
            response, evidence = snapshot(root, row)
            criterion = rubric["criteria"][label["criterion_id"]]
            if rubric["version"] != label["rubric_version"]:
                raise ValueError("Rubric version mismatch")
            budget, artifacts = Budget(settings.model_copy(update={"request_cost_cap": 1})), {}
            # Human labels and reasons are deliberately absent from the model context.
            context = {
                "stage": "judge",
                "criterion": criterion,
                "query": row["query"],
                "response": response,
                "evidence": evidence,
            }
            entry = {
                "judge_evaluation_id": uuid4().hex,
                "judge_run_id": rid,
                "response_id": row["response_id"],
                "response_sha256": row["response_sha256"],
                "evidence_sha256": row["evidence_sha256"],
                "criterion_id": label["criterion_id"],
                "rubric_version": rubric["version"],
                "judge_model": settings.model,
                "judge_prompt_version": digest((ROOT / "config/prompts/judge.md").read_text()),
                "judge_repetition": 1,
                "judged_at_utc": datetime.now(UTC).isoformat(),
            }
            try:
                output = Judgment.model_validate(
                    await run_agent("judge", context, settings, budget, trace, rid, artifacts)
                )
                if not set(output.evidence_ids) <= set(evidence):
                    raise ValueError("Judge cited unknown evidence")
                entry.update(
                    judge_label=output.label,
                    reason=output.reason,
                    supporting_evidence_ids=";".join(output.evidence_ids),
                    execution_status="completed",
                )
            except Exception as exc:
                entry.update(execution_status="error", error_category=type(exc).__name__)
            entry.update(
                cost_amount=budget.reserved_cost, cost_currency="USD", cost_basis="estimated"
            )
            append_csv(root / "judge_evaluations.csv", "judge_evaluations.csv", entry)
            write_json(root / (entry["judge_evaluation_id"] + ".json"), artifacts)
    finally:
        trace.close()
    return rid


def metrics(labels, judgments, run_id):
    predictions = {}
    for row in judgments:
        if row["judge_run_id"] != run_id:
            continue
        key = (row["response_id"], row["criterion_id"], row["rubric_version"])
        if key in predictions:
            raise ValueError("Select one judge repetition per response/criterion")
        predictions[key] = row
    counts = defaultdict(int)
    seen = set()
    for label in labels:
        if label["label_status"] != "frozen" or label["reference_label"] not in {"pass", "fail"}:
            continue
        key = (label["response_id"], label["criterion_id"], label["rubric_version"])
        if key in seen:
            raise ValueError("Duplicate reference")
        seen.add(key)
        counts["required"] += 1
        counts["human_failures"] += label["reference_label"] == "fail"
        pred = predictions.get(key)
        valid = (
            pred
            and pred["execution_status"] == "completed"
            and pred["judge_label"] in {"pass", "fail"}
        )
        if pred and any(pred[k] != label[k] for k in ("response_sha256", "evidence_sha256")):
            raise ValueError("Judgment snapshot mismatch")
        if not valid:
            counts["abstained"] += 1
            counts["errors"] += bool(pred and pred["execution_status"] != "completed")
            if label["severity"] == "critical" and label["reference_label"] == "fail":
                counts["critical_misses"] += 1
            continue
        counts["scored"] += 1
        actual, predicted = label["reference_label"] == "fail", pred["judge_label"] == "fail"
        counts[
            "tp" if actual and predicted else "fn" if actual else "fp" if predicted else "tn"
        ] += 1
        if actual and not predicted and label["severity"] == "critical":
            counts["critical_misses"] += 1

    def ratio(n, d):
        return n / d if d else None

    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    return {
        **counts,
        "positive_class": "fail",
        "precision": ratio(tp, tp + fp),
        "recall": ratio(tp, tp + fn),
        "f1": ratio(2 * tp, 2 * tp + fp + fn),
        "coverage": ratio(counts["scored"], counts["required"]),
        "failure_detection_coverage": ratio(tp, counts["human_failures"]),
        "accuracy": ratio(counts["tp"] + counts["tn"], counts["scored"]),
        "status": "descriptive_only_pending_acceptance",
        "judge_run_id": run_id,
    }


def acceptance(root, rubric_path, run_id, reviewer):
    """Produce a version-bound acceptance report; insufficient populations stay blocked."""
    import random

    root = Path(root)
    labels = read_csv(root / "adjudicated_labels.csv")
    responses = validate_labels(root, labels)
    judgments = read_csv(root / "judge_evaluations.csv")
    rubric = json.loads(Path(rubric_path).read_text())
    if rubric.get("status") != "frozen" or not reviewer.strip():
        raise ValueError("A frozen rubric and named operator review are required")
    run = [r for r in judgments if r["judge_run_id"] == run_id]
    models = {r["judge_model"] for r in run}
    prompts = {r["judge_prompt_version"] for r in run}
    prompt_hash = digest((ROOT / "config/prompts/judge.md").read_text())
    if len(models) != 1 or prompts != {prompt_hash}:
        raise ValueError("Judge configuration is inconsistent or has changed")
    slices, accepted = {}, True
    for agent in ("orchestrator", "itinerary_builder", "price_watcher", "weather_risk"):
        eligible = [label for label in labels if responses[label["response_id"]]["agent"] == agent]
        calibration = [label for label in eligible if label["split"] == "calibration"]
        holdout = [label for label in eligible if label["split"] == "judge_holdout"]
        # Count distinct response families, not correlated criterion rows or repetitions.
        by_class = {
            value: {
                label["scenario_family_id"]
                for label in holdout
                if label["reference_label"] == value
            }
            for value in ("pass", "fail")
        }
        enough = all(len(v) >= 20 for v in by_class.values()) and all(
            len(
                {
                    label["scenario_family_id"]
                    for label in calibration
                    if label["reference_label"] == value
                }
            )
            >= 10
            for value in ("pass", "fail")
        )
        result = metrics(holdout, judgments, run_id)
        gate = (
            enough
            and all(
                (result[k] or 0) >= threshold
                for k, threshold in (("precision", 0.9), ("recall", 0.9), ("coverage", 0.95))
            )
            and not result.get("critical_misses", 0)
        )
        families = sorted({label["scenario_family_id"] for label in holdout})
        intervals = {}
        if families:
            rng = random.Random(42)
            samples = defaultdict(list)
            # Cluster bootstrap: sample families with replacement and rename duplicate response keys.
            for _ in range(300):
                counts = defaultdict(int)
                for family in rng.choices(families, k=len(families)):
                    part = metrics(
                        [label for label in holdout if label["scenario_family_id"] == family],
                        judgments,
                        run_id,
                    )
                    for key in ("tp", "fp", "fn", "tn"):
                        counts[key] += part.get(key, 0)
                tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
                for name, n, d in (
                    ("precision", tp, tp + fp),
                    ("recall", tp, tp + fn),
                    ("f1", 2 * tp, 2 * tp + fp + fn),
                ):
                    if d:
                        samples[name].append(n / d)
            for name, values in samples.items():
                values.sort()
                intervals[name] = [
                    values[int(0.025 * (len(values) - 1))],
                    values[int(0.975 * (len(values) - 1))],
                ]
        # A weak criterion cannot be hidden by another criterion's larger population.
        criteria = {}
        for criterion in {label["criterion_id"] for label in holdout}:
            part = metrics(
                [label for label in holdout if label["criterion_id"] == criterion],
                judgments,
                run_id,
            )
            criteria[criterion] = part
            if any(
                (part[k] or 0) < t
                for k, t in (("precision", 0.9), ("recall", 0.9), ("coverage", 0.95))
            ):
                gate = False
        slices[agent] = {
            "metrics": result,
            "criteria": criteria,
            "family_counts": {k: len(v) for k, v in by_class.items()},
            "confidence_interval_95": intervals,
            "ci_method": "family_cluster_percentile_bootstrap_300_seed42",
            "accepted": gate,
        }
        accepted &= gate
    return {
        "accepted": accepted,
        "reviewed_by": reviewer,
        "judge_model": next(iter(models)),
        "judge_prompt_hash": prompt_hash,
        "rubric_path": str(Path(rubric_path).resolve()),
        "rubric_sha256": sha(rubric_path),
        "labels_sha256": sha(root / "adjudicated_labels.csv"),
        "judge_run_id": run_id,
        "slices": slices,
        "created_at": datetime.now(UTC).isoformat(),
    }


def record_review(root, response_id, criterion, reviewer, label, reason, rubric_version):
    root = Path(root)
    if (
        label not in {"pass", "fail", "inconclusive", "not_applicable"}
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("Explicit human label, reviewer and rationale are required")
    row = next(r for r in read_csv(root / "agent_responses.csv") if r["response_id"] == response_id)
    snapshot(root, row)
    rubric = json.loads((root / "rubric_v1.json").read_text())
    if criterion not in rubric["criteria"] or rubric["version"] != rubric_version:
        raise ValueError("Unknown criterion or rubric version")
    rid = uuid4().hex
    append_csv(
        root / "human_reviews.csv",
        "human_reviews.csv",
        {
            "review_id": rid,
            "response_id": response_id,
            "response_sha256": row["response_sha256"],
            "evidence_sha256": row["evidence_sha256"],
            "reviewer_id": reviewer,
            "reviewed_at_utc": datetime.now(UTC).isoformat(),
            "rubric_version": rubric_version,
            "criterion_id": criterion,
            "human_label": label,
            "reason": reason,
            "review_status": "submitted",
        },
    )
    return rid


def adjudicate(root, source_reviews, label, reviewer, rationale, split, severity):
    root = Path(root)
    reviews = {r["review_id"]: r for r in read_csv(root / "human_reviews.csv")}
    selected = [reviews[r] for r in source_reviews.split(";")]
    first = selected[0]
    response = next(
        r
        for r in read_csv(root / "agent_responses.csv")
        if r["response_id"] == first["response_id"]
    )
    snapshot(root, response)
    context_path = (root / response["context_ref"]).resolve()
    if not context_path.is_relative_to(root.resolve()):
        raise ValueError("Invalid context path")
    context = json.loads(context_path.read_text())
    if label not in {"pass", "fail", "inconclusive", "not_applicable"}:
        raise ValueError("Invalid reference label")
    item = {
        "label_id": uuid4().hex,
        "response_id": first["response_id"],
        "response_sha256": response["response_sha256"],
        "evidence_sha256": response["evidence_sha256"],
        "criterion_id": first["criterion_id"],
        "rubric_version": first["rubric_version"],
        "reference_label": label,
        "severity": severity,
        "source_review_ids": source_reviews,
        "adjudicator_id": reviewer,
        "adjudicated_at_utc": datetime.now(UTC).isoformat(),
        "rationale": rationale,
        "label_version": "v1",
        "label_status": "frozen",
        "split": split,
        "scenario_family_id": context["scenario_family_id"],
    }
    validate_labels(root, [*read_csv(root / "adjudicated_labels.csv"), item])
    append_csv(root / "adjudicated_labels.csv", "adjudicated_labels.csv", item)
    return item["label_id"]


def baseline(cases_path, output, repetitions, live=False):
    """Exercise the real API/runtime and freeze every outcome; expected labels stay outside context."""
    import time

    from fastapi.testclient import TestClient

    from .api import create_app

    if not 1 <= repetitions <= 3:
        raise ValueError("Baseline supports one to three repetitions")
    cases = json.loads(Path(cases_path).read_text())["cases"]
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings(
        mode="live" if live else "fixture",
        database=root / "runtime.sqlite3",
        judge_tracking=False,
        langsmith_tracing=False,
    )
    if settings.readiness():
        raise ValueError("Baseline provider configuration incomplete")
    results = []
    with TestClient(create_app(settings)) as client:
        for case in cases:
            for repetition in range(1, repetitions + 1):
                session = client.post("/sessions").json()
                headers = {"Authorization": session["capability"]}
                body = {
                    **case["input"],
                    "thread_id": session["thread_id"],
                    "client_message_id": uuid4().hex,
                }
                started = time.monotonic()
                admission = client.post("/chat", json=body, headers=headers)
                if admission.status_code != 202:
                    results.append(
                        {
                            "case_id": case["case_id"],
                            "repetition": repetition,
                            "admission_status": admission.status_code,
                            "status": "rejected",
                        }
                    )
                    continue
                rid = admission.json()["request_id"]
                while time.monotonic() - started < 160:
                    result = client.get("/requests/" + rid, headers=headers).json()
                    if result["status"] not in {"queued", "running"}:
                        break
                    time.sleep(0.1)
                if result["status"] in {"queued", "running"}:
                    results.append(
                        {"case_id": case["case_id"], "request_id": rid, "status": "harness_timeout"}
                    )
                    continue
                capture(
                    settings.database,
                    rid,
                    root / "review",
                    case["case_id"],
                    case["scenario_family_id"],
                    repetition,
                    sha(cases_path),
                )
                results.append(
                    {
                        "case_id": case["case_id"],
                        "request_id": rid,
                        "repetition": repetition,
                        "status": result["status"],
                        "latency_ms": (time.monotonic() - started) * 1000,
                    }
                )
    write_json(
        root / "baseline.json",
        {
            "cases_sha256": sha(cases_path),
            "mode": settings.mode,
            "acceptance": "not_scored_pending_human_review",
            "results": results,
        },
    )
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture_parser = sub.add_parser("capture")
    for name in ("database", "request-id", "output", "case-id", "family-id"):
        capture_parser.add_argument("--" + name, required=True)
    judge_parser = sub.add_parser("judge")
    judge_parser.add_argument("--root", required=True)
    judge_parser.add_argument("--rubric", required=True)
    judge_parser.add_argument(
        "--split", choices=["calibration", "judge_holdout", "regression"], required=True
    )
    metric_parser = sub.add_parser("metrics")
    metric_parser.add_argument("--root", required=True)
    metric_parser.add_argument("--judge-run-id", required=True)
    metric_parser.add_argument(
        "--split", choices=["calibration", "judge_holdout", "regression"], required=True
    )
    accept_parser = sub.add_parser("acceptance")
    for name in ("root", "rubric", "judge-run-id", "reviewer", "output"):
        accept_parser.add_argument("--" + name, required=True)
    review_parser = sub.add_parser("review")
    for name in (
        "root",
        "response-id",
        "criterion",
        "reviewer",
        "label",
        "reason",
        "rubric-version",
    ):
        review_parser.add_argument("--" + name, required=True)
    adjudicate_parser = sub.add_parser("adjudicate")
    for name in ("root", "source-reviews", "label", "reviewer", "rationale"):
        adjudicate_parser.add_argument("--" + name, required=True)
    adjudicate_parser.add_argument(
        "--split", required=True, choices=["calibration", "judge_holdout", "regression"]
    )
    adjudicate_parser.add_argument(
        "--severity", required=True, choices=["minor", "major", "critical"]
    )
    baseline_parser = sub.add_parser("baseline")
    baseline_parser.add_argument("--cases", required=True)
    baseline_parser.add_argument("--output", required=True)
    baseline_parser.add_argument("--repetitions", type=int, default=3)
    baseline_parser.add_argument(
        "--live", action="store_true", help="Explicitly use paid/configured providers"
    )
    args = parser.parse_args()
    if args.command == "baseline":
        print(baseline(args.cases, args.output, args.repetitions, args.live))
    elif args.command == "review":
        print(
            record_review(
                args.root,
                args.response_id,
                args.criterion,
                args.reviewer,
                args.label,
                args.reason,
                args.rubric_version,
            )
        )
    elif args.command == "adjudicate":
        print(
            adjudicate(
                args.root,
                args.source_reviews,
                args.label,
                args.reviewer,
                args.rationale,
                args.split,
                args.severity,
            )
        )
    elif args.command == "acceptance":
        report = acceptance(args.root, args.rubric, args.judge_run_id, args.reviewer)
        write_json(args.output, report)
        print(json.dumps({"accepted": report["accepted"], "report": args.output}))
    elif args.command == "capture":
        print(capture(args.database, args.request_id, args.output, args.case_id, args.family_id))
    elif args.command == "judge":
        print(asyncio.run(judge(args.root, args.rubric, args.split, Settings())))
    else:
        root = Path(args.root)
        labels = read_csv(root / "adjudicated_labels.csv")
        validate_labels(root, labels)
        predictions = read_csv(root / "judge_evaluations.csv")
        responses = {r["response_id"]: r for r in read_csv(root / "agent_responses.csv")}
        rubric_version = json.loads((root / "rubric_v1.json").read_text())["version"]
        population = [
            label
            for label in labels
            if label["split"] == args.split and label["rubric_version"] == rubric_version
        ]
        report_id = uuid4().hex
        report = {}
        for agent in sorted({responses[label["response_id"]]["agent"] for label in population}):
            agent_labels = [
                label for label in population if responses[label["response_id"]]["agent"] == agent
            ]
            for criterion in sorted({label["criterion_id"] for label in agent_labels}):
                result = metrics(
                    [label for label in agent_labels if label["criterion_id"] == criterion],
                    predictions,
                    args.judge_run_id,
                )
                report[agent + ":" + criterion] = result
                append_csv(
                    root / "metric_summaries.csv",
                    "metric_summaries.csv",
                    {
                        **result,
                        "metric_run_id": report_id,
                        "evaluation_target": "judge_reliability",
                        "split": args.split,
                        "agent": agent,
                        "criterion_or_task": criterion,
                        "aggregation": "micro",
                        "rubric_version": rubric_version,
                        "label_version": ";".join(
                            sorted({label["label_version"] for label in agent_labels})
                        ),
                        "required_count": result.get("required", 0),
                        "scored_count": result.get("scored", 0),
                        "abstained_count": result.get("abstained", 0),
                        "error_count": result.get("errors", 0),
                        "critical_failure_count": result.get("critical_misses", 0),
                        "source_results_ref": "judge_evaluations.csv",
                        "source_results_sha256": sha(root / "judge_evaluations.csv"),
                        "computed_at_utc": datetime.now(UTC).isoformat(),
                        "undefined_metrics": ";".join(
                            k
                            for k in ("precision", "recall", "f1", "coverage")
                            if result[k] is None
                        ),
                    },
                )
        write_json(root / (report_id + "-metrics.json"), report)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
