from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from jittest._llmcache import _Cache
from jittest.ledger import Candidate, Ledger


def _hold_writer(path: Path, table: str) -> tuple[sqlite3.Connection, threading.Event]:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("BEGIN IMMEDIATE")
    conn.execute(f"SELECT * FROM {table} LIMIT 1")
    release = threading.Event()

    def unlock() -> None:
        assert release.wait(2)
        conn.commit()
        conn.close()

    threading.Thread(target=unlock, daemon=True).start()
    return conn, release


def test_cache_waits_for_real_sqlite_writer(tmp_path: Path) -> None:
    path = tmp_path / "cache.db"
    cache = _Cache(path)
    assert cache.conn is not None
    assert cache.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert cache.conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000
    _writer, release = _hold_writer(path, "cache")
    threading.Timer(0.05, release.set).start()
    started = time.monotonic()
    cache.put("key", "value")
    assert time.monotonic() - started >= 0.04
    assert cache.get("key") == "value"
    cache.conn.close()


def test_ledger_waits_for_real_sqlite_writer(tmp_path: Path) -> None:
    path = tmp_path / "ledger.db"
    ledger = Ledger(path)
    assert ledger.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert ledger.conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000
    _writer, release = _hold_writer(path, "candidates")
    threading.Timer(0.05, release.set).start()
    started = time.monotonic()
    ledger.record(Candidate(repo="owned/repo", pr="1"))
    assert time.monotonic() - started >= 0.04
    assert ledger.stats()["candidates"] == 1
    ledger.close()