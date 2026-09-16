from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_START = time.time()


@dataclass(frozen=True)
class ProbeResult:
    """Immutable probe verdict. ``to_dict`` is canonical and sortable."""

    status: str
    http_status: int
    checks: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.http_status == 200

    def to_dict(self) -> dict:
        return {"status": self.status, "checks": dict(sorted(self.checks.items()))}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def _version() -> str:
    try:
        from jittest import __version__
        return str(__version__)
    except Exception:
        return "unknown"


def healthz() -> ProbeResult:
    """Liveness. Cheap, dependency-free, must never block or fan out.

    A liveness probe that touches dependencies is an outage amplifier: under
    100x load a slow dependency would cause the orchestrator to kill healthy
    pods. So this only proves the process is scheduled and responsive.
    """
    return ProbeResult("ok", 200, {"process": "alive"})


_READY_CHECKS: list[tuple[str, Callable[[], None]]] = []


def register_readiness_check(name: str, fn: Callable[[], None]) -> None:
    for idx, (existing_name, _) in enumerate(_READY_CHECKS):
        if existing_name == name:
            _READY_CHECKS[idx] = (name, fn)
            return
    _READY_CHECKS.append((name, fn))


def unregister_readiness_check(name: str) -> None:
    global _READY_CHECKS
    _READY_CHECKS = [item for item in _READY_CHECKS if item[0] != name]


def _check_core_imports() -> None:
    import jittest.integrity  # noqa: F401
    import jittest.readiness  # noqa: F401
    import jittest.receipt  # noqa: F401


def _check_schema_present() -> None:
    import jittest.receipt as _r  # noqa: F401


def _check_writable_tmp() -> None:
    import tempfile
    with tempfile.TemporaryFile() as handle:
        handle.write(b"readyz")


_BUILTIN_CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("core_imports", _check_core_imports),
    ("receipt_schema", _check_schema_present),
    ("writable_tmp", _check_writable_tmp),
]


def readyz() -> ProbeResult:
    """Readiness. Fail-closed: any failing check removes us from the pool."""
    checks: dict[str, str] = {}
    healthy = True
    for name, fn in _BUILTIN_CHECKS + _READY_CHECKS:
        try:
            fn()
            checks[name] = "ok"
        except Exception as exc:
            healthy = False
            checks[name] = f"failed: {type(exc).__name__}"
    return ProbeResult("ready" if healthy else "not_ready", 200 if healthy else 503, checks)


def build_info() -> dict:
    return {
        "service": "jittest",
        "version": _version(),
        "python": platform.python_version(),
        "pid": os.getpid(),
        "uptime_s": round(time.time() - _START, 3),
    }


class _ProbeServer(ThreadingHTTPServer):
    """Loopback probe server sized for orchestrator bursts.

    The stdlib default listen backlog is 5. Under 100 concurrent probers that
    overflows, the kernel drops SYNs and clients retransmit after ~1s, which
    showed up in chaos runs as a 1.4s P99 with transport errors. A deep
    backlog keeps accept latency flat; ``daemon_threads`` keeps shutdown clean.
    """

    request_queue_size = 1024
    daemon_threads = True
    allow_reuse_address = True


_CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Boundary sanitisation: never advertise the interpreter or stdlib version.
    server_version = "jittest"
    sys_version = ""
    # Slowloris guard: a client that opens a connection and never finishes the
    # request line/headers otherwise pins a handler thread forever (stdlib
    # default ``timeout = None``). Chaos run: 494/2000 incomplete requests hung.
    timeout = 10.0
    _ALLOW = "GET, HEAD"

    def log_message(self, fmt, *args):  # structured logging only
        from .logging import log_event
        # ``path`` is unset when the request line itself was malformed and the
        # stdlib calls send_error before parsing finished (chaos: garbage bytes).
        route = str(getattr(self, "path", "") or "").split("?", 1)[0]
        route = route if route in ("/healthz", "/readyz", "/buildinfo") else "unmatched"
        log_event("info", "http_request", route=route)

    def handle(self):  # a client that vanishes mid-request is not a server fault
        try:
            super().handle()
        except _CLIENT_GONE:
            self.close_connection = True

    def finish(self):  # guard wfile flush against client-gone RST / broken pipe
        try:
            super().finish()
        except _CLIENT_GONE:
            self.close_connection = True

    def _respond(self, code: int, body: str) -> None:
        raw = body.encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            if code == 405:
                self.send_header("Allow", self._ALLOW)
            self.end_headers()
            if self.command != "HEAD":  # HEAD: headers only, same Content-Length
                self.wfile.write(raw)
        except _CLIENT_GONE:
            self.close_connection = True

    def do_HEAD(self):  # noqa: N802  -- load balancers and uptime monitors probe with HEAD
        self.do_GET()

    def _method_not_allowed(self):
        # Same JSON contract as ProbeApp; the stdlib default is an HTML 501 page
        # that leaks server details and confuses JSON-only monitors.
        self._respond(405, json.dumps({"status": "method_not_allowed"}, sort_keys=True))

    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_TRACE = _method_not_allowed  # noqa: N815

    def send_error(self, code, message=None, explain=None):  # malformed request line / headers
        try:
            self.send_response(code, message)
            self.send_header("Content-Type", "application/json")
            body = json.dumps({"status": "bad_request", "code": int(code)}, sort_keys=True).encode()
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except _CLIENT_GONE:
            pass
        self.close_connection = True

    def do_GET(self):  # noqa: N802
        route = self.path.split("?")[0].rstrip("/") or "/"
        if route == "/healthz":
            result = healthz()
            self._respond(result.http_status, result.to_json())
        elif route == "/readyz":
            result = readyz()
            self._respond(result.http_status, result.to_json())
        elif route == "/buildinfo":
            self._respond(200, json.dumps(build_info(), sort_keys=True))
        else:
            self._respond(404, json.dumps({"status": "not_found"}, sort_keys=True))


def serve(host: str = "127.0.0.1", port: int = 8081, background: bool = False):
    """Development-only server; use bounded WSGI ProbeApp in production."""
    server = _ProbeServer((host, port), _Handler)
    if background:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread
    server.serve_forever()
    return server, None


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--once":
        print(json.dumps({"healthz": healthz().to_dict(), "readyz": readyz().to_dict(),
                          "buildinfo": build_info()}, sort_keys=True))
        return 0 if readyz().ok else 1
    host = os.environ.get("JITTEST_PROBE_HOST", "127.0.0.1")
    port = int(os.environ.get("JITTEST_PROBE_PORT", "8081"))
    serve(host, port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
