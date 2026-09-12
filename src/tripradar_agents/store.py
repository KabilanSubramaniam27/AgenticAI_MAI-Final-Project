"""Single-writer business state; result, artifacts and completed history commit together."""

import json
import secrets
import sqlite3
import time
from contextlib import contextmanager
from uuid import uuid4

from .security import digest, redact


class Store:
    def __init__(self, path, judge_profile=None):
        self.judge_profile = judge_profile
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions(
                    id TEXT PRIMARY KEY, capability TEXT NOT NULL, created REAL, touched REAL,
                    trip TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS requests(
                    id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id),
                    message_id TEXT, hash TEXT, payload TEXT, status TEXT, created REAL,
                    result TEXT, artifacts TEXT, UNIQUE(session,message_id));
                CREATE TABLE IF NOT EXISTS judge_jobs(
                    id TEXT PRIMARY KEY, request_id TEXT UNIQUE REFERENCES requests(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL,
                    charged_day TEXT, reserved REAL NOT NULL DEFAULT 0, result TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS active_thread ON requests(session)
                    WHERE status IN ('queued','running');
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self):
        sid, token, now = uuid4().hex, secrets.token_urlsafe(32), time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO sessions(id,capability,created,touched) VALUES(?,?,?,?)",
                (sid, digest(token), now, now),
            )
        return {"thread_id": sid, "capability": token}

    def authorize(self, db, sid, token):
        row = db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        if (
            not row
            or not secrets.compare_digest(row["capability"], digest(token))
            or time.time() - row["touched"] > 30 * 86400
            or time.time() - row["created"] > 90 * 86400
        ):
            raise PermissionError("Session unavailable")
        return row

    def admit(self, payload, token):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.authorize(db, payload["thread_id"], token)
            old = db.execute(
                "SELECT * FROM requests WHERE session=? AND message_id=?",
                (payload["thread_id"], payload["client_message_id"]),
            ).fetchone()
            if old:
                if old["hash"] != digest(payload):
                    raise ValueError("Message ID already has different input")
                return old["id"], False
            if (
                db.execute(
                    "SELECT COUNT(*) FROM requests WHERE status IN ('queued','running')"
                ).fetchone()[0]
                >= 4
            ):
                raise OverflowError("Request queue full")
            rid = uuid4().hex
            try:
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?,'queued',?,NULL,NULL)",
                    (
                        rid,
                        payload["thread_id"],
                        payload["client_message_id"],
                        digest(payload),
                        json.dumps(redact(payload)),
                        time.time(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("A request is already active in this thread") from exc
            db.execute(
                "UPDATE sessions SET touched=? WHERE id=?", (time.time(), payload["thread_id"])
            )
            return rid, True

    def start(self, rid):
        with self.connect() as db:
            return (
                db.execute(
                    "UPDATE requests SET status='running' WHERE id=? AND status='queued'", (rid,)
                ).rowcount
                == 1
            )

    def finish(self, rid, result, artifacts, trip, status="completed"):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
            if not row or row["status"] not in ("running", "queued"):
                return False
            active = db.execute("SELECT * FROM sessions WHERE id=?", (row["session"],)).fetchone()
            if (
                not active
                or time.time() - active["created"] > 90 * 86400
                or time.time() - active["touched"] > 30 * 86400
            ):
                return False
            # Request payload is the admitted user entry; result is its one terminal assistant entry.
            db.execute(
                "UPDATE requests SET status=?,result=?,artifacts=? WHERE id=?",
                (status, json.dumps(redact(result)), json.dumps(redact(artifacts)), rid),
            )
            if status == "completed" and trip:
                from .tracking import schedule

                schedule(db, rid, redact(result), redact(artifacts), self.judge_profile)
                db.execute(
                    "UPDATE sessions SET trip=? WHERE id=?", (json.dumps(trip), row["session"])
                )
            return True

    def get(self, rid, token):
        with self.connect() as db:
            row = db.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
            if not row:
                raise LookupError("Request unavailable")
            self.authorize(db, row["session"], token)
            return {
                "request_id": rid,
                "status": row["status"],
                "result": json.loads(row["result"]) if row["result"] else None,
            }

    def history(self, sid, token):
        with self.connect() as db:
            row = self.authorize(db, sid, token)
            records = db.execute(
                "SELECT payload,result,status FROM requests WHERE session=? "
                "AND result IS NOT NULL ORDER BY created DESC LIMIT 10",
                (sid,),
            ).fetchall()
            visible = []
            history = []
            for r in reversed(records):
                user, result = json.loads(r["payload"]), json.loads(r["result"])
                pair = [
                    {"role": "user", "content": user["message"]},
                    {"role": "assistant", "content": result.get("answer", "Request interrupted")},
                ]
                visible.extend(pair)
            completed = db.execute(
                "SELECT payload,result FROM requests WHERE session=? AND status='completed' "
                "ORDER BY created DESC LIMIT 10",
                (sid,),
            ).fetchall()
            for r in reversed(completed):
                history.extend(
                    [
                        {"role": "user", "content": json.loads(r["payload"])["message"]},
                        {"role": "assistant", "content": json.loads(r["result"])["answer"]},
                    ]
                )
            last = db.execute(
                "SELECT artifacts FROM requests WHERE session=? AND status='completed' ORDER BY created DESC LIMIT 1",
                (sid,),
            ).fetchone()
            allowances = json.loads(last["artifacts"] or "{}").get("allowances", []) if last else []
            return {
                "messages": visible,
                "model_history": history,
                "trip": json.loads(row["trip"]),
                "allowances": allowances,
            }

    def restart(self):
        with self.connect() as db:
            db.execute("UPDATE judge_jobs SET status='interrupted' WHERE status='running'")
            db.execute(
                "UPDATE requests SET status='interrupted',result=? "
                "WHERE status IN ('running','queued')",
                (json.dumps({"answer": "Server restarted. Submit a new request to try again."}),),
            )
            # Evidence retention is independent of diagnostic log rotation.
            db.execute("DELETE FROM requests WHERE created<?", (time.time() - 90 * 86400,))
            db.execute(
                "DELETE FROM sessions WHERE created<? AND id NOT IN (SELECT session FROM requests)",
                (time.time() - 90 * 86400,),
            )

    def delete(self, sid, token):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self.authorize(db, sid, token)
            db.execute("DELETE FROM requests WHERE session=?", (sid,))
            db.execute("DELETE FROM sessions WHERE id=?", (sid,))
