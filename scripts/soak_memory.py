#!/usr/bin/env python3
# Continuous-run memory soak + leak-slope profiler for jittest.
#
# Closes the 'long memory soak' gap listed in the 0.4.1 hardening closeout:
# bench_refusal_history.py measures burst concurrency, it does NOT prove
# leak-free continuous operation. This harness runs the same deterministic
# metadata pipeline for many segments, samples RSS per segment and fits a
# least-squares slope (KiB per 1000 operations) over the per-segment RSS
# floors. A floor-based slope is used because allocator high-water marks are
# noisy while floors track retained (i.e. leaked) memory.
#
# Run from checkout: PYTHONPATH=src python scripts/soak_memory.py
# Not a container/full-verify capacity claim; single process, synthetic input.
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import random
import sys
import time
from pathlib import Path

from jittest.integrity import canonical_json
from jittest.prod.bench import percentile
from jittest.verify import _refusal_phase_history

SEED = 20260916
SEGMENTS = 40
OPS_PER_SEGMENT = 2500
# KiB retained per 1000 ops above which we call it a leak. 1 KiB/1000 ops over
# a 24h continuous run at 10k ops/s would be ~ 860 MiB/day: clearly fatal.
LEAK_SLOPE_LIMIT_KIB = 1.0

RECORDS = [
    {'phase': 'base', 'revision': 'a' * 40, 'outcome': 'PASS',
     'stdout_sha256': 'b' * 64, 'exit_code': 0,
     'readiness': {'details': 'secret-canary'}},
    {'phase': 'head', 'refusal': {'details': 'secret-canary'}},
]


def rss_kib():
    # Current Linux RSS in KiB, or None where /proc is unavailable.
    try:
        for line in Path('/proc/self/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def least_squares_slope(xs, ys):
    # Deterministic OLS slope; returns 0.0 for a degenerate x range.
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom


def run_segment(index, ops, rng_seed):
    # One deterministic segment: returns (digest, latencies_ms, rss_floor).
    digest = hashlib.sha256()
    latencies = []
    floor = rss_kib()
    rng = random.Random(rng_seed + index)
    order = list(range(ops))
    rng.shuffle(order)
    for i in order:
        start = time.perf_counter()
        blob = canonical_json(_refusal_phase_history(RECORDS))
        latencies.append((time.perf_counter() - start) * 1000.0)
        if 'secret-canary' in blob:
            raise AssertionError(f'redaction regression: canary leaked at op {i}')
        digest.update(blob.encode('utf-8'))
        sample = rss_kib()
        if sample is not None and (floor is None or sample < floor):
            floor = sample
    return digest.hexdigest(), latencies, floor


def soak(segments=SEGMENTS, ops=OPS_PER_SEGMENT, seed=SEED,
         slope_limit=LEAK_SLOPE_LIMIT_KIB):
    # Continuous-run soak. Pure function of (segments, ops, seed).
    gc.collect()
    started = time.time()
    digests = []
    floors = []
    xs = []
    seg_p50 = []
    seg_p95 = []
    seg_p99 = []
    errors = 0
    for index in range(segments):
        try:
            digest, latencies, floor = run_segment(index, ops, seed)
        except Exception:
            errors += 1
            continue
        digests.append(digest)
        # Per-segment percentiles only: accumulating 100k floats would add
        # ~4 MiB of harness RSS and be misread as a product leak.
        seg_p50.append(percentile(latencies, 50))
        seg_p95.append(percentile(latencies, 95))
        seg_p99.append(percentile(latencies, 99))
        del latencies
        if floor is not None:
            floors.append(float(floor))
            xs.append(float((index + 1) * ops) / 1000.0)
    # Drop the first segment: interpreter/import warmup inflates the fit.
    fit_xs, fit_floors = (xs[1:], floors[1:]) if len(xs) > 2 else (xs, floors)
    slope = least_squares_slope(fit_xs, fit_floors)
    elapsed = time.time() - started
    total_ops = segments * ops
    report = {
        'harness': 'scripts/soak_memory.py',
        'kind': 'continuous_run_memory_soak',
        'seed': seed,
        'segments': segments,
        'ops_per_segment': ops,
        'total_ops': total_ops,
        'errors': errors,
        'distinct_digests': len(set(digests)),
        'segment_digest': digests[0] if digests else None,
        'latency_ms': {
            'p50': percentile(seg_p50, 50) if seg_p50 else None,
            'p95': percentile(seg_p95, 50) if seg_p95 else None,
            'p99': percentile(seg_p99, 50) if seg_p99 else None,
            'p99_worst_segment': max(seg_p99) if seg_p99 else None,
            'aggregation': 'median of per-segment percentiles',
        },
        'throughput_ops_s': (total_ops / elapsed) if elapsed > 0 else None,
        'elapsed_s': elapsed,
        'rss_kib': {
            'segment_floor_first': floors[0] if floors else None,
            'segment_floor_last': floors[-1] if floors else None,
            'floor_min': min(floors) if floors else None,
            'floor_max': max(floors) if floors else None,
            'segment_floor_series': floors,
        },
        'leak_slope_kib_per_1k_ops': slope,
        'leak_slope_limit_kib_per_1k_ops': slope_limit,
        'leak_suspected': bool(slope > slope_limit),
        'deterministic': len(set(digests)) == 1 and errors == 0,
        'platform': platform.platform(),
        'python': sys.version.split()[0],
        'scope_note': ('single-process synthetic metadata pipeline; not a '
                       'container or full-verify capacity claim'),
    }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='jittest continuous memory soak')
    parser.add_argument('--segments', type=int, default=SEGMENTS)
    parser.add_argument('--ops', type=int, default=OPS_PER_SEGMENT)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--out', default='')
    args = parser.parse_args(argv)
    report = soak(segments=args.segments, ops=args.ops, seed=args.seed)
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + chr(10))
    print(text)
    if report['leak_suspected'] or not report['deterministic']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
