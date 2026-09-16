"""Human-style 100x chaos harness for the jittest probe server.

Starts the real server and drives it with 100 concurrent clients doing what real
load balancers, scanners and broken proxies do -- GET/HEAD/POST/DELETE, garbage
request lines, 70KB URIs, header floods, traversal probes, slowloris -- while a
readiness dependency is failed and recovered mid-run.
"""

from __future__ import annotations

import argparse
import json
import random
import socket
import statistics
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


SHAPES = [
    lambda: b"GET /healthz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"GET /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"HEAD /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"POST /healthz HTTP/1.1" + CRLF + b"Host: x" + CRLF + b"Content-Length: 3" + CRLF + CRLF + b"abc",
    lambda: b"DELETE /readyz HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"\x16\x03\x01\x00\xff GARBAGE NOT HTTP" + CRLF + CRLF,
    lambda: b"GET /" + b"A" * 70000 + b" HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"GET /healthz HTTP/1.1" + CRLF + b"".join(b"X-%d: v" % i + CRLF for i in range(200)) + CRLF,
    lambda: b"GET /buildinfo HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
    lambda: b"GET /" + DOTDOT + b"/" + DOTDOT + b"/etc/passwd HTTP/1.1" + CRLF + b"Host: x" + CRLF + CRLF,
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=100)
    ap.add_argument("--requests", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=20260916)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    server, thread = probes.serve("127.0.0.1", 0, background=True)
    host, port = server.server_address[0], server.server_address[1]

    codes = Counter()
    lats: list[float] = []
    errors: list[str] = []
    lock = threading.Lock()
    per_client = max(1, args.requests // args.clients)

    def worker(idx: int):
        rng = random.Random(args.seed + idx)
        lc, ll, le = Counter(), [], []
        for _ in range(per_client):
            shape = rng.choice(SHAPES)
            try:
                status, ms, _ = _request(host, port, shape())
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
            try:
                s.close()
            except OSError:
                pass

    t0 = time.perf_counter()
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(args.clients)]
    threads += [threading.Thread(target=chaos), threading.Thread(target=slowloris)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0

    server.shutdown()
    thread.join(timeout=5)
    lats.sort()

    def pct(p):
        return round(lats[min(len(lats) - 1, int(len(lats) * p))], 3) if lats else None

    report = {
        "clients": args.clients,
        "requests_sent": sum(codes.values()) + len(errors),
        "status_codes": dict(sorted(codes.items())),
        "transport_errors": dict(Counter(errors)),
        "elapsed_s": round(elapsed, 3),
        "rps": round(sum(codes.values()) / elapsed, 1) if elapsed else None,
        "latency_ms": {
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "max": round(max(lats), 3) if lats else None,
            "mean": round(statistics.fmean(lats), 3) if lats else None,
        },
        "server_alive_after_chaos": probes.healthz().ok,
    }
    out = json.dumps(report, indent=2, sort_keys=True)
    print(out)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    unhandled = [c for c in codes if c not in (200, 400, 404, 405, 414, 431, 501, 503, 0)]
    return 1 if unhandled else 0


if __name__ == "__main__":
    sys.exit(main())
