import concurrent.futures as cf
import hashlib
import json
import platform
import random
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from jittest.integrity import canonical_json
from jittest.prod.bench import percentile

SEED = 20260916
JOBS = 10000
order = list(range(JOBS))
random.Random(SEED).shuffle(order)


def job(i):
    tick = time.perf_counter_ns()
    payload = {"id": i, "values": list(range(32))}
    digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    return i, digest, (time.perf_counter_ns() - tick) / 1e6


def run(workers):
    rows = []
    errors = []
    start = time.perf_counter()
    floor = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        # bounded submission, no unbounded queue and no sleeps
        for offset in range(0, JOBS, 100):
            futures = [pool.submit(job, i) for i in order[offset : offset + 100]]
            for f in cf.as_completed(futures):
                try:
                    rows.append(f.result())
                except Exception as exc:
                    errors.append(type(exc).__name__)
    elapsed = time.perf_counter() - start
    lat = [r[2] for r in rows]
    digest = hashlib.sha256(canonical_json(sorted((r[0], r[1]) for r in rows)).encode()).hexdigest()
    return {
        "workers": workers,
        "jobs": JOBS,
        "elapsed_s": elapsed,
        "errors": errors,
        "p50_ms": percentile(lat, 50),
        "p95_ms": percentile(lat, 95),
        "p99_ms": percentile(lat, 99),
        "throughput_ops_s": len(rows) / elapsed,
        "process_rss_high_water_before_kib": floor,
        "process_rss_high_water_after_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "result_digest": digest,
    }


rows = [run(1), run(100)]
out = {
    "scope": "synthetic canonical metadata, 100 configured workers vs 1; not full verify capacity; service latency excludes queue delay; RSS is process high-water, not sampled floor/ceiling",
    "seed": SEED,
    "python": platform.python_version(),
    "runs": rows,
    "deterministic": rows[0]["result_digest"] == rows[1]["result_digest"],
}
Path("concurrency.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
