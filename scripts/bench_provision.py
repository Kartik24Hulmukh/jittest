"""Reproducible fake-engine microbenchmark; NOT container/registry E2E.

Run with PYTHONPATH pointing to the checkout being measured. No pytest needed.
Latency includes queue wait; traced allocation peaks include instrumentation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jittest import provision

DIGEST = "sha256:" + "ab" * 32


class Engine:
    def __init__(self):
        self.created = 0
        self.destroyed = 0

    def inspect_digest(self, image):
        return DIGEST

    def inspect_repo_digests(self, image):
        return ["img@" + DIGEST]

    def create(self, spec):
        self.created += 1
        return str(self.created)

    def destroy(self, cid):
        self.destroyed += 1


def percentile(values, p):
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (rank - lo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--wheel-bytes", type=int, default=4096)
    parser.add_argument("--seed", type=int, default=186)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.jobs, args.workers, args.wheel_bytes) < 1:
        parser.error("workload parameters must be positive")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "requirements.txt").write_text("demo==1.0", encoding="utf-8")
        wh = root / "wh"
        wh.mkdir()
        with (wh / "demo-1.0-py3-none-any.whl").open("wb") as stream:
            left = args.wheel_bytes
            while left:
                chunk = min(left, 65536)
                stream.write(b"x" * chunk)
                left -= chunk
        plan = {"image": "img", "image_digest": DIGEST}

        def one(submitted):
            start = time.perf_counter()
            engine = Engine()
            manifest = provision.provision_in_sandbox(root, plan, engine, wh)
            assert engine.created == engine.destroyed == 2
            canonical = json.dumps(manifest.to_dict(), sort_keys=True).encode()
            end = time.perf_counter()
            return (end - start) * 1000, (end - submitted) * 1000, hashlib.sha256(canonical).hexdigest()

        for _ in range(10):
            one(time.perf_counter())
        order = list(range(args.jobs))
        random.Random(args.seed).shuffle(order)
        tracemalloc.start()
        begin = time.perf_counter()
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(one, time.perf_counter()) for _ in order]
            results = [f.result() for f in as_completed(futures)]
        seconds = time.perf_counter() - begin
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        hashes = {r[2] for r in results}
        assert len(hashes) == 1
        data = {
            "python": platform.python_version(), "platform": platform.platform(),
            "jobs": args.jobs, "workers": args.workers, "seed": args.seed,
            "wheel_bytes": args.wheel_bytes, "seconds": seconds,
            "throughput_jobs_s": args.jobs / seconds, "peak_traced_bytes": peak,
            "manifest_sha256": hashes.pop(), "correct_jobs": len(results),
            "service_ms": {label: percentile([r[0] for r in results], p) for label, p in [("p50", .5), ("p95", .95), ("p99", .99)]},
            "queue_inclusive_ms": {label: percentile([r[1] for r in results], p) for label, p in [("p50", .5), ("p95", .95), ("p99", .99)]},
            "scope": "fake engine, warm cache, tracemalloc enabled; not RSS or live container latency",
        }
        args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(data))


if __name__ == "__main__":
    main()
