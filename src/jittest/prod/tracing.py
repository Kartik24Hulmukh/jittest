from __future__ import annotations

import contextlib
import time
import uuid
from collections import deque
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any


class _Span:
    __slots__ = ("name", "trace_id", "span_id", "parent_id", "attributes",
                 "start_ns", "end_ns", "status")

    def __init__(self, name: str, trace_id: str, span_id: str, parent_id: str | None):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_id = parent_id
        self.attributes: dict[str, Any] = {}
        self.start_ns = time.perf_counter_ns()
        self.end_ns: int | None = None
        self.status = "UNSET"

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    @property
    def duration_ns(self) -> int:
        return (self.end_ns or time.perf_counter_ns()) - self.start_ns

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "status": self.status,
            "duration_ns": self.duration_ns,
            "attributes": dict(self.attributes),
        }


class Tracer:
    """OpenTelemetry-shaped tracer with a zero-dependency fallback.

    If ``opentelemetry-api`` is installed the API tracer is used (export requires a host-configured SDK). If it
    is not, the newest spans are recorded in a bounded in-process ring. Either way call sites are
    identical, so instrumentation never becomes a hard dependency and never
    raises at import time in an air-gapped research run.
    """

    def __init__(self, service: str = "jittest", max_finished: int = 1024) -> None:
        self.service = service
        if max_finished < 0:
            raise ValueError("max_finished must be nonnegative")
        self.finished: deque[_Span] = deque(maxlen=max_finished)
        self._current: ContextVar[_Span | None] = ContextVar("jittest_span", default=None)
        self._otel = None
        try:  # pragma: no cover - depends on optional extra
            from opentelemetry import trace as _otel_trace
            self._otel = _otel_trace.get_tracer(service)
        except Exception:
            self._otel = None

    @contextlib.contextmanager
    def span(self, name: str, **attributes: Any) -> Iterator[_Span]:
        parent = self._current.get()
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        current = _Span(name, trace_id, uuid.uuid4().hex[:16], parent.span_id if parent else None)
        for key, value in attributes.items():
            current.set_attribute(key, value)
        token = self._current.set(current)
        try:
            context = self._otel.start_as_current_span(name) if self._otel else contextlib.nullcontext()
            with context as otel_span:
                if otel_span is not None:
                    for key, value in attributes.items():
                        otel_span.set_attribute(key, value)
                yield current
            current.status = "OK"
        except BaseException as exc:
            current.status = "ERROR"
            current.set_attribute("exception.type", type(exc).__name__)
            raise
        finally:
            current.end_ns = time.perf_counter_ns()
            self._current.reset(token)
            self.finished.append(current)


_TRACER = Tracer()


def get_tracer(service: str = "jittest") -> Tracer:
    return _TRACER if service == _TRACER.service else Tracer(service)


def span(name: str, **attributes: Any):
    return _TRACER.span(name, **attributes)
