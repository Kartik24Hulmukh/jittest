import argparse
import concurrent.futures
import gc
import hashlib
import json
import math
import platform
import random
import resource
import subprocess
import time
import tracemalloc

from jittest.integrity import build_integrity_record, compare_runs


def run(jobs, workers, seed):
    rng = random.Random(seed)
    inputs = [rng.randbytes(rng.choice([64, 1024, 16384])) for _ in range(jobs)]

    def one(data):
        start = time.perf_counter_ns()
        a = build_integrity_record(
            data, "sha256:" + "ab" * 32, "demo==1", "none", ["test"], 0, data
        )
        b = build_integrity_record(
            data, "sha256:" + "ab" * 32, "demo==1", "none", ["test"], 0, data
        )
        result = compare_runs(a, b)
        assert result["reproducible"]
        return (time.perf_counter_ns() - start) / 1e6, result["first_digest"]

    gc.collect()
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, inputs))
    elapsed = time.perf_counter() - start
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    latencies = sorted(t for t, _ in results)
    digest = hashlib.sha256("".join(d for _, d in results).encode()).hexdigest()
    return {
        "jobs": jobs,
        "workers": workers,
        "seed": seed,
        "p50_ms": latencies[math.ceil(jobs * 0.50) - 1],
        "p95_ms": latencies[math.ceil(jobs * 0.95) - 1],
        "p99_ms": latencies[math.ceil(jobs * 0.99) - 1],
        "throughput_jobs_s": jobs / elapsed,
        "elapsed_s": elapsed,
        "tracemalloc_peak_bytes": peak,
        "retained_bytes_including_results": current - before,
        "rss_max_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "result_sha256": digest,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "method": "service latency includes tracemalloc; excludes queue wait; fixed-seed integrity build+compare microbenchmark, NOT end-to-end SaaS capacity",
        "runs": [run(n, w, 20260913) for n, w in [(100, 1), (10000, 32)]],
    }
    with open(args.output, "w") as f:
        json.dump(report, f, indent=2)
