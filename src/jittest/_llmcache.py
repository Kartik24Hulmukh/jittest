"""On-disk response cache, so re-running a pull request costs nothing."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ._sqlite import connect_sqlite

__all__ = ["_Cache"]


@dataclass
class _Flight:
    lock: threading.RLock = field(default_factory=threading.RLock)
    users: int = 0


_FLIGHTS: dict[tuple[str, str], _Flight] = {}
_FLIGHTS_LOCK = threading.Lock()


def _retain_flight(token: tuple[str, str]) -> _Flight:
    with _FLIGHTS_LOCK:
        flight = _FLIGHTS.setdefault(token, _Flight())
        flight.users += 1
        return flight


def _release_flight(token: tuple[str, str], flight: _Flight) -> None:
    with _FLIGHTS_LOCK:
        flight.users -= 1
        if flight.users == 0 and _FLIGHTS.get(token) is flight:
            del _FLIGHTS[token]


class _Cache:
    def __init__(self, path: Path | str | None) -> None:
        self.conn = None
        self._lock = threading.RLock()
        self.identity: str | None = None
        if not path:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.identity = str(p.resolve())
        self.conn = connect_sqlite(p, cross_thread=True)
        with self.conn:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, at REAL)")

    def get(self, key: str) -> str | None:
        if not self.conn:
            return None
        with self._lock:
            row = self.conn.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        if not self.conn:
            return
        with self._lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                (key, value, time.time()),
            )

    @contextmanager
    def singleflight(self, key: str) -> Iterator[None]:
        """Serialize one cache miss per process and release failed leaders."""
        if self.identity is None:
            yield
            return
        token = (self.identity, key)
        flight = _retain_flight(token)
        flight.lock.acquire()
        try:
            yield
        finally:
            flight.lock.release()
            _release_flight(token, flight)
