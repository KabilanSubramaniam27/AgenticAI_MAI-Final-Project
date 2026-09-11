"""Summary-only local events and optional, best-effort LangSmith spans."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import uuid4

from rich.console import Console

from .config import Settings
from .utils import now


class Observer:
    def __init__(self, settings: Settings, run_id: str, attempt_id: str | None = None):
        self.settings = settings
        self.run_id = run_id
        self.attempt_id = attempt_id or uuid4().hex
        self.path = settings.data / "reports" / run_id / "events.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stack: list[Any] = []
        self.events: list[dict] = []
        self.client: Any = None
        self.trace_id: str | None = None
        self.trace_url: str | None = None
        self.telemetry = "disabled"
        self.console = Console(stderr=True)
        if settings.langsmith_tracing:
            try:
                if not settings.langsmith_api_key.get_secret_value():
                    raise ValueError("Missing LangSmith key")
                from langsmith import Client

                # The SDK otherwise includes key suffixes and request context in failure logs.
                logging.getLogger("langsmith").setLevel(logging.CRITICAL)
                self.client = Client(
                    api_key=settings.langsmith_api_key.get_secret_value(),
                    api_url=settings.langsmith_endpoint,
                    workspace_id=settings.langsmith_workspace_id or None,
                    hide_inputs=True,
                    hide_outputs=True,
                    timeout_ms=3000,
                )
                self.telemetry = "pending"
            except Exception:
                self.telemetry = "unavailable"
                self.console.print("LangSmith unavailable; continuing with local events.")

    def event(self, stage: str, **fields: Any) -> None:
        event = {
            "time": now(),
            "ingestion_run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "stage": stage,
            **fields,
        }
        self.events.append(event)
        with self.path.open("a") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        if fields.get("event") == "finished":
            self.console.print(
                f"{stage}: {fields.get('outcome', 'success')} "
                f"({fields.get('elapsed_ms', 0):.0f} ms)"
            )

    @contextmanager
    def span(self, name: str, run_type: str = "chain", **metadata: Any) -> Iterator[dict]:
        summary: dict[str, Any] = {}
        started = time.monotonic()
        run = None
        self.event(name, event="started", **metadata)
        if self.client:
            try:
                from langsmith.run_trees import RunTree

                fields: dict[str, Any] = dict(
                    name=name,
                    run_type=run_type,
                    inputs={},
                    extra={
                        "metadata": {
                            "ingestion_run_id": self.run_id,
                            "attempt_id": self.attempt_id,
                            **metadata,
                        }
                    },
                    tags=["tripradar", name],
                )
                run = (
                    self.stack[-1].create_child(**fields)
                    if self.stack
                    else RunTree(
                        **fields,
                        project_name=self.settings.langsmith_project,
                        ls_client=self.client,
                    )
                )
                run.post()
                if not self.stack:
                    self.trace_id = str(run.id)
                self.stack.append(run)
            except Exception:
                run = None
                self.telemetry = "unavailable"
        error = None
        try:
            yield summary
        except BaseException as exc:
            # Never serialize arbitrary exceptions/headers into external telemetry.
            error = type(exc).__name__
            summary.update(outcome="failed", error_type=error)
            raise
        finally:
            summary.setdefault("outcome", "success")
            summary["elapsed_ms"] = (time.monotonic() - started) * 1000
            self.event(name, event="finished", **{**metadata, **summary})
            if run:
                try:
                    run.add_metadata(summary)
                    run.end(
                        outputs={},
                        error=error
                        or (
                            "Partial ingestion failure"
                            if summary["outcome"] == "partial_failure"
                            else None
                        ),
                    )
                    run.patch()
                except Exception:
                    self.telemetry = "unavailable"
                finally:
                    self.stack.pop()

    def close(self) -> None:
        if not self.client:
            return

        def flush() -> None:
            try:
                self.client.flush()
                if self.trace_id:
                    # Readback confirms delivery before claiming a dashboard URL.
                    run = self.client.read_run(self.trace_id)
                    self.trace_url = self.client.get_run_url(run=run)
                    self.telemetry = "confirmed"
            except Exception:
                self.telemetry = "delivery_unconfirmed"

        worker = threading.Thread(target=flush, daemon=True)
        worker.start()
        worker.join(timeout=5)
        if worker.is_alive():
            self.telemetry = "delivery_unconfirmed"
