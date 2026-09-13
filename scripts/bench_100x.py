#!/usr/bin/env python3
"""Fixed-seed 100x stress + chaos benchmark for jittest core pipelines.

Run:  PYTHONPATH=src python3 scripts/bench_100x.py --out docs/benchmarks/prod-100x.json

Every number this prints is recomputable: the workload is derived from a
fixed seed, percentiles are nearest-rank, and the export is canonical JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from jittest import integrity  # noqa: E402
from jittest.prod import bench, probes  # noqa: E402
from jittest.prod.logging import JsonLogger  # noqa: E402
from jittest.prod.tracing import Tracer  # noqa: E402

LOG = JsonLogger("jittest.bench", run_id="bench-100x")


def _payload(rng, index):
    return {
        "index": index,
        "digest": f"sha256:{rng.getrandbits(256):064x}",
        "files": sorted(f"f{rng.randrange(10_000)}" for _ in range(8)),
        "nested": {"a": rng.random(), "b": [rng.randrange(100) for _ in range(5)]},
    }


def bench_canonical_json(iterations: int):
    return bench.run_benchmark(
        "integrity.canonical_json",
        lambda rng, i: integrity.canonical_json(_payload(rng, i)),
        iterations=iterations, warmup=50,
    )


def bench_sha256(iterations: int):
    return bench.run_benchmark(
        "integrity.sha256_bytes",
        lambda rng, i: integrity.sha256_bytes(integrity.canonical_json(_payload(rng, i)).encode()),
        iterations=iterations, warmup=50,
    )


def bench_probes(iterations: int):
    return bench.run_benchmark(
        "prod.readyz", lambda rng, i: probes.readyz(), iterations=iterations, warmup=20
    )


def concurrency_invariant(jobs: int = 2000, workers: int = 64) -> dict:
    """100x burst: identical input must yield one and only one digest."""
    tracer = Tracer("jittest.bench")
    fixed = {"schema": integrity.SCHEMA_VERSION, "payload": "canonical", "n": list(range(32))}
    digests = set()
    lock = threading.Lock()
    panics = []

    def job(_i):
        try:
            with tracer.span("integrity.digest"):
                digest = integrity.sha256_bytes(integrity.canonical_json(fixed).encode())
            with lock:
                digests.add(digest)
        except BaseException as exc:  # chaos must never surface as a panic
            with lock:
                panics.append(type(exc).__name__)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(job, range(jobs)))
    return {"jobs": jobs, "workers": workers, "distinct_digests": len(digests),
            "unhandled_panics": len(panics), "spans_closed": len(tracer.finished)}


def chaos_probe_storm(iterations: int = 500) -> dict:
    """Inject a failing dependency mid-flight; readyz must fail closed, then recover."""
    healthy_before = probes.readyz().ok
    probes.register_readiness_check("chaos_io_drop", lambda: (_ for _ in ()).throw(OSError("io drop")))
    degraded = [probes.readyz().http_status for _ in range(iterations)]
    probes._READY_CHECKS.clear()
    recovered = [probes.readyz().http_status for _ in range(iterations)]
    return {
        "healthy_before": healthy_before,
        "degraded_all_503": set(degraded) == {503},
        "recovered_all_200": set(recovered) == {200},
        "deterministic_recovery": len(set(recovered)) == 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=2000)
    parser.add_argument("--out", default="docs/benchmarks/prod-100x.json")
    args = parser.parse_args()

    results = [bench_canonical_json(args.iterations), bench_sha256(args.iterations),
               bench_probes(max(args.iterations // 4, 100))]
    invariants = {"concurrency": concurrency_invariant(), "chaos": chaos_probe_storm()}
    for result in results:
        LOG.info("benchmark", **result.to_dict())

    payload = {"schema": "jittest.bench/1", "seed": bench.DEFAULT_SEED,
               "results": [r.to_dict() for r in results], "invariants": invariants}
    blob = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    directory = os.path.dirname(args.out)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(blob)
    print(blob)
    ok = (invariants["concurrency"]["distinct_digests"] == 1
          and invariants["concurrency"]["unhandled_panics"] == 0
          and all(invariants["chaos"][k] for k in ("degraded_all_503", "recovered_all_200")))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
