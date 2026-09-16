"""Human-style 100x chaos harness for the jittest probe server.

Starts the real server and drives it with 100 concurrent clients across 10 distinct
real-human personas (load balancers, uptime monitors, confused devs, broken proxies,
pathological URIs, header flooders, scanners, impatient cancellers, trickle writers,
and mixed humans) while a readiness dependency is failed and recovered mid-run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import resource
import socket
import statistics
import struct
import sys
import threading
import time
from collections import Counter

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


def _execute_persona(persona: str, host: int, port: int, rng: random.Random) -> tuple[int, float]:
    if persona == "load_balancer":
        st, ms, _ = _request(host, port, SHAPES["healthz"]())
    elif persona == "uptime_monitor":
        st, ms, _ = _request(host, port, SHAPES["head_readyz"]())
    elif persona == "confused_dev":
        shape = rng.choice([SHAPES["post_healthz"], SHAPES["delete_readyz"]])
        st, ms, _ = _request(host, port, shape())
    elif persona == "broken_proxy":
        st, ms, _ = _request(host, port, SHAPES["garbage"]())
    elif persona == "pathological_uri":
        st, ms, _ = _request(host, port, SHAPES["pathological_uri"]())
    elif persona == "header_flooder":
        st, ms, _ = _request(host, port, SHAPES["header_flood"]())
    elif persona == "scanner":
        st, ms, _ = _request(host, port, SHAPES["scanner"]())
    elif persona == "impatient_canceller":
        st, ms, _ = _request_rst(host, port, SHAPES["healthz"]())
    elif persona == "trickle_writer":
        st, ms, _ = _request_trickle(host, port, SHAPES["healthz"]())
    else:  # mixed_human
        shape_fn = rng.choice(list(SHAPES.values()))
        st, ms, _ = _request(host, port, shape_fn())
    return st, ms


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=100)
    ap.add_argument("--requests", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    rss_floor = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    # Intercept stderr to catch any unhandled tracebacks
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

    server, thread = probes.serve("127.0.0.1", 0, background=True)
    host, port = server.server_address[0], server.server_address[1]

    codes = Counter()
    lats: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()
    per_client = max(1, args.requests // args.clients)

    # Assign each client to a persona deterministically
    swarm_rng = random.Random(args.seed)
    client_personas = [swarm_rng.choice(PERSONAS) for _ in range(args.clients)]
    persona_counts = Counter(client_personas)

    def worker(idx: int, persona: str):
        rng = random.Random(args.seed + idx)
        lc, ll, le = Counter(), [], []
        for _ in range(per_client):
            try:
                status, ms = _execute_persona(persona, host, port, rng)
                lc[status] += 1
                ll.append(ms)
            except OSError as exc:
                le.append(type(exc).__name__)
        with lock:
            codes.update(lc)
            lats.extend(ll)
            errors.extend(le)

    failing = {"on": False}

    def flaky():
        if failing["on"]:
            raise RuntimeError("synthetic dependency outage")

    probes.register_readiness_check("chaos_dependency", flaky)

    def chaos():
        time.sleep(1.0)
        failing["on"] = True
        time.sleep(1.5)
        failing["on"] = False

    def slowloris(n=50):
        socks = []
        for _ in range(n):
            try:
                s = socket.create_connection((host, port), timeout=5)
                s.sendall(b"GET /healthz HTTP/1.1" + CRLF)
                socks.append(s)
            except OSError:
                pass
        time.sleep(3)
        for s in socks:
            with contextlib.suppress(OSError):
                s.close()

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i, client_personas[i])) for i in range(args.clients)]
    threads += [threading.Thread(target=chaos), threading.Thread(target=slowloris)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    server.shutdown()
    thread.join(timeout=5)
    sys.stderr = real_stderr
    lats.sort()

    rss_ceiling = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
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
        "rss_floor_kb": rss_floor,
        "rss_ceiling_kb": rss_ceiling,
        "server_alive_after_chaos": probes.healthz().ok,
    }
    out = json.dumps(report, indent=2, sort_keys=True)
    print(out)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    unhandled = [c for c in codes if c not in (200, 400, 404, 405, 414, 431, 501, 503, 0)]
    return 1 if unhandled or traceback_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
