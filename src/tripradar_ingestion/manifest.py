"""Durable stage checkpoints with verified artifact hashes."""

import sqlite3
from pathlib import Path
from typing import Any

from .utils import file_hash, now


class Manifest:
    def __init__(self, data: Path):
        path = data / "manifests/ingestion.sqlite3"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS stages (
            destination TEXT, stage TEXT, fingerprint TEXT, path TEXT, checksum TEXT,
            completed_at TEXT, PRIMARY KEY(destination, stage))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS checks (
            destination TEXT PRIMARY KEY, checked_at TEXT, status TEXT)""")
        self.db.commit()

    def cached(self, destination: str, stage: str, fingerprint: str) -> Path | None:
        row = self.db.execute(
            "SELECT fingerprint,path,checksum FROM stages WHERE destination=? AND stage=?",
            (destination, stage),
        ).fetchone()
        if row and row[0] == fingerprint and Path(row[1]).is_file():
            if file_hash(Path(row[1])) == row[2]:
                return Path(row[1])
        return None

    def record(self, destination: str, stage: str, fingerprint: str, path: Path) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO stages VALUES (?,?,?,?,?,?)",
                (destination, stage, fingerprint, str(path), file_hash(path), now()),
            )

    def checked(self, destination: str, status: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO checks VALUES (?,?,?)", (destination, now(), status)
            )

    def checks(self) -> list[dict[str, Any]]:
        return [
            dict(zip(("destination", "checked_at", "status"), row, strict=True))
            for row in self.db.execute("SELECT * FROM checks ORDER BY destination")
        ]

    def close(self) -> None:
        self.db.close()
