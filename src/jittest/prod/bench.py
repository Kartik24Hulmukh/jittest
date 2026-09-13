from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_SEED = 20260913


def percentile(samples: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile. Deterministic, no interpolation ambiguity."""
    if not samples:
        raise ValueError("percentile() requires at least one sample")
    ordered = sorted(samples)
    if pct <= 0:
        return ordered[0]
    if pct >= 100:
        return ordered[-1]
    rank = int(-(-pct / 100.0 * len(ordered) // 1))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def derive_seed(seed: int, index: int, tag: str = "") -> int:
    """Derive a per-iteration integer seed.

    Python 3.14 removed support for tuple seeds, and more importantly a
    tuple seed was never guaranteed stable across versions. Hashing to a
    64-bit integer makes the workload reproducible across interpreters,
    which is the actual research-grade requirement.
    """
    material = f"{seed}:{index}:{tag}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def rss_kb() -> int:
    try:
        import resource
    except ImportError:
        return -1  # unavailable on Windows; never represent as measured zero
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(usage / 1024) if sys.platform == "darwin" else int(usage)


@dataclass(frozen=True)
class BenchResult:
    name: str
    seed: int
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    throughput_ops_s: float
    rss_delta_kb: int
    wall_s: float

    def to_dict(self) -> dict:
        return dict(sorted(asdict(self).items()))

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def run_benchmark(name: str, fn: Callable[[random.Random, int], Any],
                  iterations: int = 1000, seed: int = DEFAULT_SEED,
                  warmup: int = 0) -> BenchResult:
    """Fixed-seed benchmark: same seed -> same workload, every time.

    ``fn`` receives a seeded ``random.Random`` and the iteration index. The
    RNG is re-derived per iteration from (seed, index) so that the workload
    is order-independent and therefore safe to reproduce or shard.
    """
    for index in range(warmup):
        fn(random.Random(derive_seed(seed, index, "warmup")), index)
    rss_before = rss_kb()
    latencies: list[float] = []
    started = time.perf_counter()
    for index in range(iterations):
        rng = random.Random(derive_seed(seed, index))
        tick = time.perf_counter()
        fn(rng, index)
        latencies.append((time.perf_counter() - tick) * 1000.0)
    wall = time.perf_counter() - started
    return BenchResult(
        name=name,
        seed=seed,
        iterations=iterations,
        p50_ms=round(percentile(latencies, 50), 6),
        p95_ms=round(percentile(latencies, 95), 6),
        p99_ms=round(percentile(latencies, 99), 6),
        max_ms=round(max(latencies), 6),
        throughput_ops_s=round(iterations / wall, 3) if wall > 0 else float("inf"),
        rss_delta_kb=rss_kb() - rss_before if rss_before >= 0 else -1,
        wall_s=round(wall, 6),
    )


def export_metrics(results: Sequence[BenchResult], path: str) -> str:
    """Write a canonical, byte-reproducible metrics export."""
    payload: dict[str, Any] = {
        "schema": "jittest.bench/1",
        "results": [r.to_dict() for r in results],
    }
    blob = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(blob)
    return blob
