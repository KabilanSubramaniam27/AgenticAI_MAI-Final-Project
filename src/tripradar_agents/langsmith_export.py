"""Explicit sanitized LangSmith export; never enable raw framework auto-tracing."""

import logging
from datetime import datetime
from queue import Empty, Full, Queue
from threading import Event, Thread
from uuid import UUID

from .security import redact


def export_trace(client, settings, bundle):
    from langsmith.run_trees import RunTree

    bundle = redact(bundle)  # Second boundary before creating any SDK run object.
    events = bundle["events"]
    root = RunTree(
        id=UUID(bundle["request_id"]),
        name="tripradar.request",
        run_type="chain",
        project_name=settings.langsmith_project,
        ls_client=client,
        start_time=datetime.fromisoformat(bundle["started"]),
        inputs=bundle["input"],
        tags=["tripradar", settings.mode],
        extra={
            "metadata": {
                "request_id": bundle["request_id"],
                "thread_id": bundle["input"]["thread_id"],
                "environment": settings.mode,
                "export": "redacted-v1",
                "provider": settings.provider,
                "model": settings.model,
                "specialist_model": settings.specialist_model,
            }
        },
    )
    root.end(
        outputs=bundle["output"],
        error=bundle.get("error"),
        end_time=datetime.fromisoformat(bundle["ended"]),
    )
    parents = {}
    for role in (
        "orchestrator",
        "itinerary_builder",
        "price_watcher",
        "weather_risk",
        "grounding_verifier",
    ):
        own = [e for e in events if e.get("agent") == role]
        if not own:
            continue
        parent = (
            root
            if role in ("orchestrator", "grounding_verifier")
            else parents.get("orchestrator", root)
        )
        parents[role] = parent.create_child(
            role,
            "chain",
            start_time=datetime.fromisoformat(own[0]["time"]),
            end_time=datetime.fromisoformat(own[-1]["time"]),
            inputs={},
            outputs={"status": "see child spans"},
        )
    pending = {}
    finished = {}
    for event in events:
        kind = event["event"]
        role = event.get("agent", "orchestrator")
        parent = parents.get(role, root)
        if kind in ("llm.input", "tool.start"):
            key = event.get("call_id") or (role, event.get("tool"))
            name = "llm." + role if kind == "llm.input" else event["tool"]
            run = parent.create_child(
                name,
                "llm" if kind == "llm.input" else "tool",
                start_time=datetime.fromisoformat(event["time"]),
                inputs=event,
            )
            pending[key] = run
        elif kind in ("llm.output", "llm.error", "tool.end", "tool.error"):
            key = event.get("call_id") or (role, event.get("tool"))
            if run := pending.pop(key, None) or finished.get(key):
                run.end(
                    outputs=event,
                    error=event.get("error") or ("ToolError" if kind == "tool.error" else None),
                    end_time=datetime.fromisoformat(event["time"]),
                )
                finished[key] = run
        elif kind == "rag.end":
            parent.create_child(
                "destination.search",
                "retriever",
                inputs={"query": event["query"]},
                outputs={"evidence_ids": event["evidence_ids"]},
                start_time=datetime.fromisoformat(event["time"]),
                end_time=datetime.fromisoformat(event["time"]),
            )
    for run in pending.values():
        run.end(
            error="Interrupted or missing terminal event",
            end_time=datetime.fromisoformat(bundle["ended"]),
        )

    # Post completed runs synchronously on our worker, with batching disabled, so failures
    # are observable here. Preserve parent IDs without relying on ambient tracing context.
    def post(run):
        run.post()
        for child in run.child_runs:
            post(child)

    post(root)
    # Confirm root visibility before reporting a dashboard link; children can still be delayed.
    stored = client.read_run(root.id)
    return client.get_run_url(run=stored)


class Exporter:
    def __init__(self, settings, report, export=export_trace, client_factory=None):
        self.settings, self.report, self.export = settings, report, export
        self.queue = Queue(maxsize=32)
        self.stopping = Event()
        self.status = "disabled"
        self.client = None
        self.worker = None
        if not settings.langsmith_tracing:
            return
        if not settings.langsmith_api_key.get_secret_value():
            self.status = "missing_api_key"
            return
        try:
            from langsmith import Client
            from urllib3.util import Retry

            # SDK exception logs can contain payloads/auth suffixes; emit safe status ourselves.
            logging.getLogger("langsmith").setLevel(logging.CRITICAL)
            self.client = (client_factory or Client)(
                api_key=settings.langsmith_api_key.get_secret_value(),
                api_url=settings.langsmith_endpoint,
                workspace_id=settings.langsmith_workspace_id or None,
                auto_batch_tracing=False,
                timeout_ms=2000,
                retry_config=Retry(total=0),
                hide_inputs=redact,
                hide_outputs=redact,
                hide_metadata=redact,
                omit_traced_runtime_info=True,
            )
            self.status = "configured_delivery_unconfirmed"
            self.worker = Thread(target=self._run, daemon=True, name="tripradar-langsmith")
            self.worker.start()
        except Exception:
            self.status = "unavailable"

    def submit(self, bundle):
        if not self.worker:
            return
        try:
            self.queue.put_nowait(redact(bundle))
        except Full:
            self.status = "queue_full"
            self.report("langsmith.degraded", request_id=bundle["request_id"], status=self.status)

    def _run(self):
        while not self.stopping.is_set() or not self.queue.empty():
            try:
                bundle = self.queue.get(timeout=0.1)
            except Empty:
                continue
            try:
                url = self.export(self.client, self.settings, bundle)
                self.status = "root_confirmed"
                self.report("langsmith.exported", request_id=bundle["request_id"], trace_url=url)
            except Exception:
                self.status = "delivery_unconfirmed"
                self.report(
                    "langsmith.degraded", request_id=bundle["request_id"], status=self.status
                )
            finally:
                self.queue.task_done()

    def close(self):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=5)
            if self.worker.is_alive():
                self.status = "shutdown_delivery_unconfirmed"
                self.report("langsmith.degraded", status=self.status)
