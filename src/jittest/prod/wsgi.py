"""Small, dependency-free WSGI operational probes for a worker deployment.

These report worker state, NOT dependency compatibility or a GA certification.
The supervisor must mark ready only after its required initialization succeeds.
Serve behind a bounded production WSGI server; this module starts no threads.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from typing import Any


class ProbeApp:
    """Thread-safe cached probes; no user code, network or disk checks per request.

    ``tracer`` is an optional OpenTelemetry-compatible tracer, configured by the
    host. The host owns exporter queues/shutdown. No global logging changes.
    """

    def __init__(self, *, logger: logging.Logger | None = None, tracer: Any = None):
        self._lock = threading.Lock()
        self._ready = False
        self._draining = False
        self._logger = logger or logging.getLogger("jittest.probes")
        self._tracer = tracer

    def set_ready(self, ready: bool) -> None:
        """Publish supervisor initialization state; draining is irreversible."""
        if not isinstance(ready, bool):
            raise TypeError("ready must be bool")
        with self._lock:
            self._ready = ready and not self._draining

    def drain(self) -> None:
        """Withdraw readiness before stopping admission and draining jobs."""
        with self._lock:
            self._draining = True
            self._ready = False

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        start = time.perf_counter()
        path = environ.get("PATH_INFO", "")
        route = path if path in ("/healthz", "/readyz") else "unmatched"
        method = environ.get("REQUEST_METHOD", "GET")
        with self._lock:
            ready = self._ready
        if route == "unmatched":
            status, payload = "404 Not Found", {"error": "not_found"}
        elif method not in ("GET", "HEAD"):
            status, payload = "405 Method Not Allowed", {"error": "method_not_allowed"}
        elif route == "/healthz":
            status, payload = "200 OK", {"status": "alive"}
        else:
            status = "200 OK" if ready else "503 Service Unavailable"
            payload = {"status": "ready" if ready else "not_ready"}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        # Observability is best-effort and must never change a probe's verdict.
        # Never record arbitrary URLs, headers, credentials, bodies or exceptions.
        try:
            context = self._tracer.start_as_current_span("jittest.probe") if self._tracer else nullcontext()
            with context as span:
                if span is not None:
                    span.set_attribute("http.route", route)
                    span.set_attribute("http.response.status_code", int(status[:3]))
            self._logger.info(json.dumps({
                "event": "probe", "route": route, "status": int(status[:3]),
                "duration_ms": round((time.perf_counter() - start) * 1000, 3),
            }, sort_keys=True, separators=(",", ":")))
        except Exception:
            pass
        headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body))),
                   ("Cache-Control", "no-store")]
        if status.startswith("405"):
            headers.append(("Allow", "GET, HEAD"))
        start_response(status, headers)
        return [b"" if method == "HEAD" else body]
