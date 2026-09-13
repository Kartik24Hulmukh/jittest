"""jittest production-grade observability and readiness surface.

This package is additive and import-safe: it has zero third-party hard
dependencies and never mutates core pipeline behaviour. It exists to make
jittest operable as a production SaaS (probes, structured logs, traces)
while preserving research-grade determinism (fixed-seed benchmarks with
verifiable metric exports).
"""

from .bench import BenchResult, percentile, run_benchmark
from .logging import JsonLogger, log_event
from .probes import ProbeResult, healthz, readyz, serve
from .tracing import get_tracer, span
from .wsgi import ProbeApp

__all__ = [
    "ProbeApp",
    "JsonLogger",
    "log_event",
    "healthz",
    "readyz",
    "ProbeResult",
    "serve",
    "get_tracer",
    "span",
    "BenchResult",
    "percentile",
    "run_benchmark",
]
