"""Human-style 100x chaos harness for the jittest probe server.

Starts the real server and drives it with 100 concurrent clients, each bound to a
distinct scenario record from a deterministic matrix of 10 real-human personas x 4
network conditions x 3 header profiles (120 records) (load balancers, uptime monitors, confused devs, broken proxies,
pathological URIs, header flooders, scanners, impatient cancellers, trickle writers,
and mixed humans) while a readiness dependency is failed and recovered mid-run. Fault injection is
driven by request-progress barriers (no wall-clock sleeps) and recovery latency is
measured monotonically from fault clearance to the first 200 on /readyz.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import itertools
import json
import random
import socket
import statistics
import struct
import sys
import threading
import time
from collections import Counter

try:  # POSIX only; Windows CI imports this module through the test suite
    import resource
except ImportError:  # pragma: no cover
    resource = None

from jittest.prod import logging as prod_logging
from jittest.prod import probes

CRLF = b"\r\n"
DOTDOT = b"." * 2


def _request(host, port, raw, timeout=5.0):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(raw)
        buf = b""
        while CRLF + CRLF not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        status = int(buf.split()[1]) if buf.startswith(b"HTTP/") else 0
        return status, (time.perf_counter() - t0) * 1000.0, buf
    finally:
        s.close()


def _request_rst(host, port, raw, timeout=5.0):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(raw[: len(raw) // 2] if len(raw) > 4 else raw)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        return 0, (time.perf_counter() - t0) * 1000.0, b""
    finally:
        s.close()


def _request_trickle(host, port, raw, timeout=5.0):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        for chunk in [raw[:10], raw[10:25], raw[25:]]:
            if chunk:
                s.sendall(chunk)
                time.sleep(0.005)
        buf = b""
        s.settimeout(timeout)
        while CRLF + CRLF not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        status = int(buf.split()[1]) if buf.startswith(b"HTTP/") else 0
        return status, (time.perf_counter() - t0) * 1000.0, buf
    finally:
        s.close()


SHAPES = {
    "healthz": lambda: b"GET /healthz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "readyz": lambda: b"GET /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "head_readyz": lambda: b"HEAD /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "post_healthz": lambda: b"POST /healthz HTTP/1.1" + CRLF + b"Host: x" + CRLF + b"Content-Length: 3" + CRLF + CRLF + b"abc",
    "delete_readyz": lambda: b"DELETE /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "garbage": lambda: b"\x16\x03\x01\x00\xff GARBAGE NOT HTTP" + CRLF + CRLF,
    "pathological_uri": lambda: b"GET /" + b"A" * 70000 + b" HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "header_flood": lambda: b"GET /healthz HTTP/1.1" + CRLF + b"".join(b"X-%d: v" % i + CRLF for i in range(200)) + CRLF,
    "buildinfo": lambda: b"GET /buildinfo HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    "scanner": lambda: b"GET /" + DOTDOT + b"/" + DOTDOT + b"/etc/passwd HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
}

PERSONAS = [
    "broken_proxy",
    "confused_dev",
    "header_flooder",
    "impatient_canceller",
    "load_balancer",
    "mixed_human",
    "pathological_uri",
    "scanner",
    "trickle_writer",
    "uptime_monitor",
]

# Network conditions a real client sits behind. Each changes the bytes-on-wire
# timeline, not just a label: direct, a slow uplink, a half-close after the
# request, and a mid-request RST from an impatient browser/proxy.
NETWORKS = ["direct", "slow_uplink", "half_close", "rst_midway"]

# Header profiles seen from real edges: bare k8s probes, browsers with cookies,
# and proxies that inject forwarding/trace headers.
HEADER_PROFILES = {
    "bare": b"",
    "browser": (
        b"User-Agent: Mozilla/5.0" + CRLF
        + b"Accept: text/html,application/json" + CRLF
        + b"Cookie: session=abc123; theme=dark" + CRLF
    ),
    "proxy": (
        b"X-Forwarded-For: 203.0.113.9" + CRLF
        + b"traceparent: 00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01" + CRLF
        + b"Via: 1.1 edge-proxy" + CRLF
    ),
}


def scenario_matrix() -> list[dict]:
    """Deterministic 120-record scenario catalogue (persona x network x headers).

    Every record is a distinct (role, network condition, header profile) tuple,
    so 100 clients drawn from it are 100 distinct scenarios rather than 100
    workers relabelled as personas.
    """
    records = []
    for idx, (persona, network, profile) in enumerate(
        itertools.product(PERSONAS, NETWORKS, sorted(HEADER_PROFILES))
    ):
        records.append(
            {"id": idx, "persona": persona, "network": network, "headers": profile}
        )
    return records


def _inject_headers(raw: bytes, profile: str) -> bytes:
    extra = HEADER_PROFILES[profile]
    if not extra or not raw.startswith((b"GET", b"HEAD", b"POST", b"DELETE")):
        return raw
    line_end = raw.index(CRLF) + len(CRLF)
    return raw[:line_end] + extra + raw[line_end:]


def _request_half_close(host, port, raw, timeout=5.0):
    t0 = time.perf_counter()
    s = socket.create_connection((host, port), timeout=timeout)
    try:
        s.sendall(raw)
        s.shutdown(socket.SHUT_WR)  # client is done talking, still wants the answer
        buf = b""
        while CRLF + CRLF not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        status = int(buf.split()[1]) if buf.startswith(b"HTTP/") else 0
        return status, (time.perf_counter() - t0) * 1000.0, buf
    finally:
        s.close()


_TRANSPORT = {
    "direct": _request,
    "slow_uplink": _request_trickle,
    "half_close": _request_half_close,
    "rst_midway": _request_rst,
}


def _persona_shape(persona: str, rng: random.Random) -> bytes:
    if persona == "load_balancer":
        return SHAPES["healthz"]()
    if persona == "uptime_monitor":
        return SHAPES["head_readyz"]()
    if persona == "confused_dev":
        return rng.choice([SHAPES["post_healthz"], SHAPES["delete_readyz"]])()
    if persona == "broken_proxy":
        return SHAPES["garbage"]()
    if persona == "pathological_uri":
        return SHAPES["pathological_uri"]()
    if persona == "header_flooder":
        return SHAPES["header_flood"]()
    if persona == "scanner":
        return SHAPES["scanner"]()
    if persona in ("impatient_canceller", "trickle_writer"):
        return SHAPES["healthz"]()
    return rng.choice(list(SHAPES.values()))()  # mixed_human


def _execute_scenario(scenario: dict, host, port, rng: random.Random) -> tuple[int, float]:
    raw = _inject_headers(_persona_shape(scenario["persona"], rng), scenario["headers"])
    network = scenario["network"]
    if scenario["persona"] == "impatient_canceller":
        network = "rst_midway"
    elif scenario["persona"] == "trickle_writer":
        network = "slow_uplink"
    st, ms, _ = _TRANSPORT[network](host, port, raw)
    return st, ms


def _execute_persona(persona: str, host, port, rng: random.Random) -> tuple[int, float]:
    """Backwards-compatible single-persona entry point (direct network, bare headers)."""
    return _execute_scenario(
        {"persona": persona, "network": "direct", "headers": "bare"}, host, port, rng
    )


class Progress:
    """Monotonic request counter with barrier waits. Replaces wall-clock sleeps so
    fault injection happens at a deterministic point in the load, not at a time
    that drifts with machine speed."""

    def __init__(self) -> None:
        self._n = 0
        self._cv = threading.Condition()
        self.finished = False

    def tick(self) -> None:
        with self._cv:
            self._n += 1
            self._cv.notify_all()

    def finish(self) -> None:
        with self._cv:
            self.finished = True
            self._cv.notify_all()

    def wait_for(self, count: int, timeout: float = 60.0) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: self._n >= count or self.finished, timeout)


class JsonLogSink(io.StringIO):
    """Captures structured stdout logs and validates every line is one JSON object."""

    def __init__(self) -> None:
        super().__init__()
        self.lines = 0
        self.bad = 0
        self.leaks = 0
        self._lock = threading.Lock()

    def write(self, s: str) -> int:
        with self._lock:
            for line in s.splitlines():
                if not line:
                    continue
                self.lines += 1
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict) or "event" not in obj:
                        self.bad += 1
                except ValueError:
                    self.bad += 1
                if "ghp_" in line or "Traceback" in line:
                    self.leaks += 1
        return len(s)


def _probe_until(host, port, raw, want_status: int, deadline_s: float) -> float | None:
    """Hammer a probe until it returns want_status; return monotonic ms elapsed or None."""
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            st, _, _ = _request(host, port, raw, timeout=2.0)
        except OSError:
            continue
        if st == want_status:
            return round((time.perf_counter() - t0) * 1000.0, 3)
    return None


def _rss_kb() -> int:
    """Peak RSS in KiB; 0 where getrusage is unavailable (Windows)."""
    if resource is None:
        return 0
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=100)
    ap.add_argument("--requests", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--json", default=None)
    ap.add_argument("--recovery-slo-ms", type=float, default=200.0)
    args = ap.parse_args(argv)

    rss_floor = _rss_kb()

    stderr_buf = io.StringIO()
    real_stderr = sys.stderr

    class StderrInterceptor:
        def write(self, s):
            stderr_buf.write(s)
            real_stderr.write(s)

        def flush(self):
            stderr_buf.flush()
            real_stderr.flush()

    sys.stderr = StderrInterceptor()

    # Route the server's structured stdout logs into a validating sink so the
    # harness report stays machine-readable and log ingestion is verified.
    log_sink = JsonLogSink()
    saved_logger = prod_logging._DEFAULT
    prod_logging._DEFAULT = prod_logging.JsonLogger(stream=log_sink, run_id="chaos")

    server, thread = probes.serve("127.0.0.1", 0, background=True)
    host, port = server.server_address[0], server.server_address[1]

    codes = Counter()
    lats: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()
    per_client = max(1, args.requests // args.clients)
    total = per_client * args.clients
    progress = Progress()

    matrix = scenario_matrix()
    swarm_rng = random.Random(args.seed)
    order = list(range(len(matrix)))
    swarm_rng.shuffle(order)
    client_scenarios = [matrix[order[i % len(matrix)]] for i in range(args.clients)]
    persona_counts = Counter(s["persona"] for s in client_scenarios)
    distinct = len({(s["persona"], s["network"], s["headers"]) for s in client_scenarios})

    def worker(idx: int, scenario: dict):
        rng = random.Random(args.seed + idx)
        lc, ll, le = Counter(), [], []
        for _ in range(per_client):
            try:
                status, ms = _execute_scenario(scenario, host, port, rng)
                lc[status] += 1
                ll.append(ms)
            except OSError as exc:
                le.append(type(exc).__name__)
            progress.tick()
        with lock:
            codes.update(lc)
            lats.extend(ll)
            errors.extend(le)

    failing = threading.Event()

    def flaky():
        if failing.is_set():
            raise RuntimeError("synthetic dependency outage")

    probes.register_readiness_check("chaos_dependency", flaky)
    recovery = {"degrade_ms": None, "recovery_ms": None}
    readyz_raw = SHAPES["readyz"]()

    def chaos():
        progress.wait_for(int(total * 0.15))  # fault at 15% of offered load
        failing.set()
        recovery["degrade_ms"] = _probe_until(host, port, readyz_raw, 503, 5.0)
        progress.wait_for(int(total * 0.45))  # clear at 45% of offered load
        failing.clear()
        recovery["recovery_ms"] = _probe_until(host, port, readyz_raw, 200, 5.0)

    def slowloris(n=50):
        socks = []
        for _ in range(n):
            try:
                s = socket.create_connection((host, port), timeout=5)
                s.sendall(b"GET /healthz HTTP/1.1" + CRLF)
                socks.append(s)
            except OSError:
                pass
        progress.wait_for(int(total * 0.70))  # hold half-open sockets through 70% of load
        for s in socks:
            with contextlib.suppress(OSError):
                s.close()

    t0 = time.perf_counter()
    threads = [
        threading.Thread(target=worker, args=(i, client_scenarios[i])) for i in range(args.clients)
    ]
    aux = [threading.Thread(target=chaos), threading.Thread(target=slowloris)]
    for t in threads + aux:
        t.start()
    for t in threads:
        t.join()
    progress.finish()
    for t in aux:
        t.join(timeout=10)
    elapsed = time.perf_counter() - t0

    server.shutdown()
    thread.join(timeout=5)
    probes.unregister_readiness_check("chaos_dependency")
    sys.stderr = real_stderr
    prod_logging._DEFAULT = saved_logger
    lats.sort()

    rss_ceiling = _rss_kb()
    traceback_count = stderr_buf.getvalue().count("Traceback")

    def pct(p):
        return round(lats[min(len(lats) - 1, int(len(lats) * p))], 3) if lats else None

    report = {
        "clients": args.clients,
        "requests_sent": sum(codes.values()) + len(errors),
        "status_codes": dict(sorted(codes.items())),
        "transport_errors": dict(Counter(errors)),
        "stderr_tracebacks": traceback_count,
        "elapsed_s": round(elapsed, 3),
        "rps": round(sum(codes.values()) / elapsed, 1) if elapsed else None,
        "latency_ms": {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "max": round(max(lats), 3) if lats else None,
            "mean": round(statistics.fmean(lats), 3) if lats else None,
        },
        "personas": dict(sorted(persona_counts.items())),
        "scenario_matrix_size": len(matrix),
        "distinct_client_scenarios": distinct,
        "recovery": {
            "degrade_ms": recovery["degrade_ms"],
            "recovery_ms": recovery["recovery_ms"],
            "slo_ms": args.recovery_slo_ms,
        },
        "structured_logs": {
            "lines": log_sink.lines,
            "invalid_json": log_sink.bad,
            "secret_or_traceback_leaks": log_sink.leaks,
        },
        "rss_floor_kb": rss_floor,
        "rss_ceiling_kb": rss_ceiling,
        "server_alive_after_chaos": probes.healthz().ok,
        "seed": args.seed,
    }
    out = json.dumps(report, indent=2, sort_keys=True)
    print(out)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    unhandled = [c for c in codes if c not in (200, 400, 404, 405, 414, 431, 501, 503, 0)]
    rec = recovery["recovery_ms"]
    ok = (
        not unhandled
        and not errors
        and traceback_count == 0
        and report["server_alive_after_chaos"]
        and log_sink.bad == 0
        and log_sink.leaks == 0
        and distinct >= min(args.clients, len(matrix))
        and rec is not None
        and rec <= args.recovery_slo_ms
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
