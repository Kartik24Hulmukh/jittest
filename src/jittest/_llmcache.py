"""On-disk response cache, so re-running a pull request costs nothing."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

__all__ = ["_Cache"]


class _Cache:
    def __init__(self, path: Path | str | None) -> None:
        self.conn = None
        if not path:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, at REAL)")
        self.conn.commit()

    def get(self, key: str) -> str | None:
        if not self.conn:
            return None
        row = self.conn.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        if not self.conn:
            return
        self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                          (key, value, time.time()))
        self.conn.commit()
