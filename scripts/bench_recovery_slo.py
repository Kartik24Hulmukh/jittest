#!/usr/bin/env python3
"""Fixed recovery-SLO harness for the run_bounded timeout path.

Recovery = t_join_end - t_wait_end of a timed-out run, measured under CPU
contention (8 busy-loop burners). Workload is deterministic: 100 calls of a
30 s sleep at timeout=0.2 s across 20 workers. Nearest-rank percentiles.

Run: PYTHONPATH=src python3 scripts/bench_recovery_slo.py --out FILE.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import resource
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from jittest.proc import run_bounded  # noqa: E402

CALLS = 100
WORKERS = 20
TIMEOUT = 0.2
BURN = "import time\nt = time.monotonic()\nwhile time.monotonic() - t < 90:\n    pass\n"


def nearest_rank(values, pct):
    if not values:
        return None
    rank = max(1, math.ceil(pct / 100 * len(values)))
    return round(values[rank - 1], 3)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None)
    parser.add_argument("--burners", type=int, default=8)
    args = parser.parse_args()
    burners = [subprocess.Popen([sys.executable, "-c", BURN]) for _ in range(args.burners)]
    try:
        deadline_settle = time.monotonic() + 0.3
        while time.monotonic() < deadline_settle:
            pass
        before = set(threading.enumerate())
        recoveries = []
        errors = []
        lock = threading.Lock()
        t0 = time.perf_counter()

        def call(index):
            try:
                run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=TIMEOUT)
                with lock:
                    errors.append(f"call {index}: no timeout raised")
            except subprocess.TimeoutExpired as exc:
                with lock:
                    recoveries.append((exc.t_join_end - exc.t_wait_end) * 1000)
            except BaseException as exc:  # noqa: BLE001 - harness records everything
                with lock:
                    errors.append(f"call {index}: {exc!r}")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(call, range(CALLS)))
        wall = time.perf_counter() - t0
        leaked = sorted(t.name for t in threading.enumerate() if t not in before)
        rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    finally:
        for burner in burners:
            burner.kill()
        for burner in burners:
            burner.wait()
    values = sorted(recoveries)
    report = {
        "harness": "bench_recovery_slo",
        "calls": CALLS,
        "workers": WORKERS,
        "burners": args.burners,
        "timeout_s": TIMEOUT,
        "recovery_ms": {
            "p50": nearest_rank(values, 50),
            "p95": nearest_rank(values, 95),
            "p99": nearest_rank(values, 99),
            "worst": nearest_rank(values, 100),
        },
        "throughput_timedout_runs_per_s": round(CALLS / wall, 2),
        "rss_ceiling_kib": rss_kib,
        "errors": errors,
        "leaked_threads": leaked,
        "bar_recovery_ms": 200.0,
        "passed": bool(values) and not errors and not leaked and values[-1] < 200.0,
    }
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
