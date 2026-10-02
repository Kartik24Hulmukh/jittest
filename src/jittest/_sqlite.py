"""Shared bounded SQLite connection policy for local Jittest state."""
from __future__ import annotations

import sqlite3
from pathlib import Path

BUSY_TIMEOUT_MS = 30_000


def connect_sqlite(
    path: Path | str,
    *,
    cross_thread: bool = False,
) -> sqlite3.Connection:
    """Open SQLite with bounded writer waiting and WAL concurrency."""
    conn = sqlite3.connect(
        str(path),
        timeout=BUSY_TIMEOUT_MS / 1000,
        check_same_thread=not cross_thread,
    )
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=WAL")
    except Exception:
        conn.close()
        raise
    return conn