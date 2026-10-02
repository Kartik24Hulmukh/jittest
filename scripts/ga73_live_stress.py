"""Bounded, opt-in live routing evidence. Never substitutes for catch/FPR/PR cost.

MELIOUS_API_KEY must be supplied through the environment, never argv. Each job
makes a 256-token bounded request with truncation escalation disabled. Provider
errors remain in the artifact; there is no success-only rerun filtering.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from jittest._pricing import price_for
from jittest.melious import (
    DEFAULT_MAX_INFLIGHT_PER_MODEL,
    DeadlineExceeded,
    MeliousError,
    MeliousRouter,
)

MODELS = ("glm-5.3", "glm-5.3-flash", "kimi-k3", "qwen3.8-27b")


def rss_kib() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        pass
    return None


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--calls", type=int, default=100)
    ap.add_argument("--workers", type=int, default=100)
    ap.add_argument("--deadline", type=float, default=30.0)
    ap.add_argument("--max-inflight-per-model", type=int,
                    default=DEFAULT_MAX_INFLIGHT_PER_MODEL)
    ap.add_argument("--out", type=Path, default=Path("live-routing.json"))
    return ap


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not 4 <= args.calls <= 100 or not 1 <= args.workers <= 100:
        parser.error("calls must be 4..100; workers must be 1..100")
    if not math.isfinite(args.deadline) or not 0 < args.deadline <= 30:
        parser.error("deadline must be finite, positive and <=30 seconds")
    if not 1 <= args.max_inflight_per_model <= 100:
        parser.error("max-inflight-per-model must be 1..100")
    if not os.getenv("MELIOUS_API_KEY"):
        parser.error("MELIOUS_API_KEY is required")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    diff = subprocess.check_output(["git", "diff", "HEAD"])
    rows: list[dict] = []
    start_rss, start_threads = rss_kib(), threading.active_count()
    t0 = time.monotonic()
    with MeliousRouter(max_inflight_per_model=args.max_inflight_per_model) as router:
        try:
            catalogue = router.list_models()
            missing = sorted(set(MODELS) - set(catalogue))
            rows.append({"case": "catalogue", "status": "ok" if not missing else "failed",
                         "model_count": len(catalogue), "missing": missing})
        except Exception as exc:
            rows.append({"case": "catalogue", "status": "failed", "error_type": type(exc).__name__})
            catalogue = []
        if set(MODELS) <= set(catalogue):
            def one(index: int) -> dict:
                model = MODELS[index % len(MODELS)]
                expected = f"JT-{index:03d}"
                started = time.monotonic()
                try:
                    result = router.complete(model, f"Reply exactly {expected}. No punctuation or explanation.",
                                             deadline=args.deadline, max_tokens=256,
                                             truncation_escalation=False)
                    price = price_for("melious/" + result.model)
                    inp = result.usage.get("prompt_tokens", 0)
                    out = max(result.usage.get("completion_tokens", 0),
                              result.usage.get("total_tokens", 0) - inp)
                    return {"case": "completion", "index": index, "model": model,
                            "routed_model": result.model,
                            "status": "ok" if result.text.strip() == expected and result.finish_reason == "stop" else "failed",
                            "seconds": time.monotonic() - started, "attempts": result.attempts,
                            "finish_reason": result.finish_reason, "usage": result.usage,
                            "provider_billing": result.provider_billing,
                            "list_price_estimate_usd": None if price is None else (inp * price[0] + out * price[1]) / 1e6}
                except Exception as exc:
                    return {"case": "completion", "index": index, "model": model, "status": "failed",
                            "seconds": time.monotonic() - started, "error_type": type(exc).__name__,
                            "error_detail": str(exc) if isinstance(exc, MeliousError) else "unexpected exception",
                            "cause_type": type(exc.__cause__).__name__ if exc.__cause__ else None,
                            "list_price_estimate_usd": None}
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for future in as_completed([pool.submit(one, i) for i in range(args.calls)]):
                    rows.append(future.result())
            started = time.monotonic()
            try:
                router.complete(MODELS[0], "No network call allowed.", deadline=0)
                passed = False
            except DeadlineExceeded:
                passed = True
            rows.append({"case": "invalid_deadline", "status": "ok" if passed else "failed",
                         "seconds": time.monotonic() - started})
    completions = [r for r in rows if r["case"] == "completion"]
    durations = sorted(r["seconds"] for r in completions)
    quantiles = {f"p{p}_seconds": durations[max(0, math.ceil(len(durations) * p / 100) - 1)]
                 for p in (50, 95, 99)} if durations else {}
    failures = sum(r["status"] != "ok" for r in rows)
    elapsed = time.monotonic() - t0
    evidence = {"sha": sha, "working_diff_sha256": hashlib.sha256(diff).hexdigest(),
                "calls_requested": args.calls, "workers": args.workers,
                "deadline_seconds": args.deadline,
                "max_inflight_per_model": args.max_inflight_per_model, "max_tokens": 256,
                "truncation_escalation": False, "seconds": elapsed,
                "successful_completions": sum(r["status"] == "ok" for r in completions),
                "failed_checks": failures, "passed": failures == 0 and len(completions) == args.calls,
                "latency_includes_failures": True, **quantiles,
                "throughput_calls_per_second": len(completions) / elapsed,
                "rss_start_kib": start_rss, "rss_end_kib": rss_kib(),
                "threads_before": start_threads, "threads_after": threading.active_count(),
                "cost_caveat": "Provider-reported token counts times list prices, not wallet reconciliation or USD per PR. Failed calls may have unobserved spend.",
                "rows": rows}
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({k: v for k, v in evidence.items() if k != "rows"}, indent=2))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
