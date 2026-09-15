#!/usr/bin/env python3
"""Synthetic metadata stress, NOT full verify or container capacity evidence.

Run from checkout: PYTHONPATH=src python scripts/bench_refusal_history.py
RSS floor/ceiling are sampled current Linux RSS, not ru_maxrss differences.
"""
from __future__ import annotations

import hashlib
import json
import platform
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jittest.integrity import canonical_json
from jittest.prod.bench import percentile
from jittest.verify import _refusal_phase_history

SEED = 20260916
JOBS = 10000
WORKERS = 100  # 100x a one-worker baseline, not a measured production load.
RECORDS = [{"phase": "base", "revision": "a" * 40, "outcome": "PASS",
            "stdout_sha256": "b" * 64, "exit_code": 0,
            "readiness": {"details": "secret-canary"}},
           {"phase": "head", "refusal": {"details": "secret-canary"}}]


def rss_kib():
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def measure(workers):
    stop = threading.Event()
    memory = []
    def sample():
        while not stop.is_set():
            value = rss_kib()
            if value is not None:
                memory.append(value)
            stop.wait(0.005)
    thread = threading.Thread(target=sample)
    thread.start()
    order = list(range(JOBS))
    random.Random(SEED).shuffle(order)
    def job(index):
        # Force randomized completion order without nondeterministic inputs.
        delay = random.Random(SEED + index).randrange(5) / 100000
        time.sleep(delay)
        start = time.perf_counter()
        blob = canonical_json(_refusal_phase_history(RECORDS))
        assert "secret-canary" not in blob
        digest = hashlib.sha256(blob.encode()).hexdigest()
        return (time.perf_counter() - start) * 1000, digest
    latencies, digests, errors = [], set(), []
    start = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(job, i) for i in order]
            for future in as_completed(futures):
                try:
                    latency, digest = future.result()
                    latencies.append(latency)
                    digests.add(digest)
                except Exception as exc:
                    errors.append(type(exc).__name__)
    finally:
        stop.set()
        thread.join()
    wall = time.perf_counter() - start
    return {"workers": workers, "jobs": JOBS, "completed": len(latencies),
            "errors": errors, "digests": sorted(digests),
            "p50_ms": round(percentile(latencies, 50), 6),
            "p95_ms": round(percentile(latencies, 95), 6),
            "p99_ms": round(percentile(latencies, 99), 6),
            "throughput_jobs_s": round(len(latencies) / wall, 3),
            "rss_floor_kib": min(memory) if memory else None,
            "rss_ceiling_kib": max(memory) if memory else None,
            "wall_s": round(wall, 6)}


def main():
    results = [measure(1), measure(WORKERS)]
    print(json.dumps({"schema": "jittest.refusal-stress/1", "seed": SEED,
                      "python": platform.python_version(), "results": results,
                      "latency_scope": "metadata transform+hash only; excludes queue and injected delay",
                      "rss_scope": "whole process sampled every 5ms; includes executor/future allocations"},
                     sort_keys=True, indent=2))
    return 0 if all(r["completed"] == JOBS and not r["errors"] and
                    len(r["digests"]) == 1 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
