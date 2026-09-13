from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from typing import Any, TextIO

_REDACT_KEYS = ("token", "secret", "password", "authorization", "api_key", "apikey")


def _redact(key: str, value: Any) -> Any:
    if any(marker in key.lower() for marker in _REDACT_KEYS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(str(k), v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact("", item) for item in value]
    return value


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return "[UNSERIALIZABLE]"


class JsonLogger:
    """Structured, single-line JSON logger.

    Every record is one canonical JSON object on one line so that log
    shippers never have to reassemble multi-line output. Keys are sorted so
    that two identical events are byte-identical -- a research-grade
    determinism requirement, not a cosmetic one.
    """

    def __init__(self, service: str = "jittest", stream: TextIO | None = None,
                 clock=None, run_id: str | None = None) -> None:
        self._lock = threading.Lock()
        self.service = service
        self._stream = stream if stream is not None else sys.stderr
        self._clock = clock or time.time
        self.run_id = run_id or os.environ.get("JITTEST_RUN_ID") or uuid.uuid4().hex

    def record(self, level: str, event: str, **fields: Any) -> dict:
        payload = {
            "ts": round(float(self._clock()), 6),
            "level": level.upper(),
            "service": self.service,
            "run_id": self.run_id,
            "event": event,
        }
        for key, value in fields.items():
            payload[key] = _jsonable(_redact(key, value))
        return payload

    def emit(self, level: str, event: str, **fields: Any) -> dict:
        payload = self.record(level, event, **fields)
        with self._lock:
            self._stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            self._stream.flush()
        return payload

    def info(self, event: str, **fields: Any) -> dict:
        return self.emit("info", event, **fields)

    def warning(self, event: str, **fields: Any) -> dict:
        return self.emit("warning", event, **fields)

    def error(self, event: str, **fields: Any) -> dict:
        return self.emit("error", event, **fields)


_DEFAULT = JsonLogger()


def log_event(level: str, event: str, **fields: Any) -> dict:
    return _DEFAULT.emit(level, event, **fields)
