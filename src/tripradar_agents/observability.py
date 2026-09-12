"""One queued file writer; sanitized artifacts remain independently retained in SQLite."""

import json
import logging
import queue
import sys
import time
from datetime import UTC, datetime
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

from .langsmith_export import Exporter
from .security import digest, redact


class Writer(RotatingFileHandler):
    def __init__(self, path):
        super().__init__(path, maxBytes=10_000_000, backupCount=5)
        self.definitions = set()
        self.degraded = False
        for backup in path.parent.glob(path.name + ".*"):
            if backup.is_file() and time.time() - backup.stat().st_mtime > 14 * 86400:
                backup.unlink()
        if path.exists() and time.time() - path.stat().st_mtime > 14 * 86400:
            self.doRollover()

    def handleError(self, record):
        self.degraded = True
        print("TripRadar local tracing degraded", file=sys.stderr)

    def emit(self, record):
        try:
            entry = json.loads(record.getMessage())
            if self.shouldRollover(record):
                self.doRollover()
                self.definitions.clear()
            if entry.get("event") == "llm.input":
                definition = {key: entry.pop(key) for key in ("system", "tools") if key in entry}
                key = digest(definition)
                if key not in self.definitions:
                    header = logging.makeLogRecord(
                        {
                            "msg": json.dumps({"event": "llm.definition", "id": key, **definition}),
                            "levelno": logging.INFO,
                        }
                    )
                    super().emit(header)
                    self.definitions.add(key)
                entry["definition_ref"] = key
            updated = logging.makeLogRecord(
                {"msg": json.dumps(entry, default=str), "levelno": logging.INFO}
            )
            super().emit(updated)
        except Exception:
            self.handleError(record)


class Admission(QueueHandler):
    def __init__(self, pending, writer):
        super().__init__(pending)
        self.writer = writer

    def handleError(self, record):
        self.writer.degraded = True
        print("TripRadar logging queue full; local trace is incomplete", file=sys.stderr)


class Trace:
    """MCP observations are forwarded at the client boundary, never written by child processes."""

    def __init__(self, path, settings=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.logger = logging.Logger(str(path))
        self.writer = Writer(path)
        self.pending = queue.Queue(maxsize=1000)
        self.logger.addHandler(Admission(self.pending, self.writer))
        self.listener = QueueListener(self.pending, self.writer)
        self.listener.start()
        self.requests = {}
        self.exporter = Exporter(settings, self.event) if settings else None

    def begin(self, rid, payload):
        if self.exporter and self.exporter.worker:
            self.requests[rid] = {
                "request_id": rid,
                "input": redact(payload),
                "started": datetime.now(UTC).isoformat(),
                "events": [],
            }

    def finish(self, rid, output, error=None):
        self.event("request.end", request_id=rid, status=output.get("status"), error=error)
        bundle = self.requests.pop(rid, None)
        if bundle:
            bundle.update(output=redact(output), error=error, ended=datetime.now(UTC).isoformat())
            self.exporter.submit(bundle)

    @property
    def telemetry(self):
        if self.writer.degraded:
            return "degraded_local_logging"
        return self.exporter.status if self.exporter else "disabled"

    def event(self, event, **data):
        entry = {"event": event, "time": datetime.now(UTC).isoformat(), **redact(data)}
        self.logger.info(json.dumps(entry, default=str))
        if bundle := self.requests.get(data.get("request_id")):
            bundle["events"].append(entry)

    def close(self):
        if self.exporter:
            self.exporter.close()
        # Drain bounded queue before closing the one file owner.
        deadline = time.monotonic() + 5
        try:
            self.pending.put(self.listener._sentinel, timeout=5)
        except queue.Full:
            self.writer.degraded = True
        self.listener._thread.join(timeout=max(0, deadline - time.monotonic()))
        if self.listener._thread.is_alive():
            self.writer.degraded = True
        else:
            self.writer.close()
        for handler in self.logger.handlers:
            handler.close()
