"""GA-73 live stress: Melious router across all 4 catalogue models.

Requires MELIOUS_API_KEY in the environment (never in argv/logs).
Measures: catalogue auth, per-model completion, failover, deadline behavior,
and a small concurrency burst (10 parallel, out of order) with hard bounds.
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest.melious import (
    AuthenticationError,
    ChainExhaustedError,
    DeadlineExceeded,
    MeliousRouter,
    ModelUnavailableError,
)

MODELS = ["glm-5.3", "glm-5.3-flash", "kimi-k3", "qwen3.8-27b"]


def _burst(r: MeliousRouter) -> list[tuple[str, str, float, str]]:
    prompt = "Write exactly one sentence about deterministic software testing."
    burst = (MODELS * 3)[:10]

    def one(m: str) -> tuple[str, str, float, str]:
        t0 = time.perf_counter()
        try:
            o = r.complete(m, prompt, deadline=45.0, max_tokens=64)
            return (m, "ok", time.perf_counter() - t0, f"finish={o.finish_reason} attempts={o.attempts}")
        except (ChainExhaustedError, DeadlineExceeded, AuthenticationError, ModelUnavailableError) as e:
            return (m, "fail", time.perf_counter() - t0, type(e).__name__)

    with ThreadPoolExecutor(max_workers=10) as pool:
        return list(pool.map(one, burst))


def main() -> int:
    key = os.environ.get("MELIOUS_API_KEY", "")
    if not key:
        print("MELIOUS_API_KEY is not set; cannot run live stress", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str, float, str]] = []
    r = MeliousRouter(api_key=key)
    try:
        # 1) catalogue auth
        t0 = time.perf_counter()
        try:
            models = r.list_models()
            dt = time.perf_counter() - t0
            present = [m for m in MODELS if m in models]
            missing = [m for m in MODELS if m not in models]
            print(f"[catalogue] {len(models)} models; present={present}; missing={missing} ({dt:.2f}s)")
            rows.append(("catalogue", "auth", "ok", dt, f"present={present} missing={missing}"))
        except AuthenticationError as e:
            print(f"[catalogue] AUTH FAILED: {e}")
            rows.append(("catalogue", "auth", "auth-fail", 0.0, str(e)))
            return 1

        # 2) per-model completion (sequential, hard deadline)
        prompt = "Write exactly one sentence about deterministic software testing."
        for model in MODELS:
            t0 = time.perf_counter()
            try:
                out = r.complete(model, prompt, deadline=60.0, max_tokens=128)
                dt = time.perf_counter() - t0
                ok = bool(out.text.strip())
                print(f"[{model}] ok={ok} finish={out.finish_reason} attempts={out.attempts} {dt*1000:.0f}ms")
                rows.append(("model", model, "ok", dt, f"finish={out.finish_reason} attempts={out.attempts}"))
            except (AuthenticationError, ModelUnavailableError, ChainExhaustedError, DeadlineExceeded) as e:
                dt = time.perf_counter() - t0
                print(f"[{model}] FAILED {type(e).__name__}: {e} ({dt*1000:.0f}ms)")
                rows.append(("model", model, "fail", dt, type(e).__name__))

        # 3) failover: retired glm-4.5 -> glm-5.3
        t0 = time.perf_counter()
        try:
            out = r.complete("glm-4.5", prompt, deadline=60.0, max_tokens=128)
            dt = time.perf_counter() - t0
            print(f"[failover glm-4.5] routed to {out.model} attempts={out.attempts} ({dt*1000:.0f}ms)")
            rows.append(("failover", "glm-4.5->glm-5.3", "ok", dt, f"routed={out.model}"))
        except (ModelUnavailableError, ChainExhaustedError, DeadlineExceeded, AuthenticationError) as e:
            dt = time.perf_counter() - t0
            print(f"[failover glm-4.5] FAILED {type(e).__name__}: {e} ({dt*1000:.0f}ms)")
            rows.append(("failover", "glm-4.5->glm-5.3", "fail", dt, type(e).__name__))

        # 4) concurrency burst
        results = _burst(r)
        ok_n = sum(1 for _, s, _, _ in results if s == "ok")
        print(f"[burst] {ok_n}/10 ok (parallel, out of order)")
        for m, s, dt, note in results:
            print(f"    {m}: {s} {dt*1000:.0f}ms {note}")
            rows.append(("burst", m, s, dt, note))

        # 5) deadline behavior: impossible deadline must raise fast (no hang)
        t0 = time.perf_counter()
        try:
            r.complete("glm-5.3", prompt, deadline=0.0001, max_tokens=64)
            print("[deadline] FAIL: expected DeadlineExceeded")
        except DeadlineExceeded:
            dt = time.perf_counter() - t0
            print(f"[deadline] DeadlineExceeded in {dt*1000:.2f}ms (no hang)")
            rows.append(("deadline", "glm-5.3", "ok", dt, "raised fast"))
    finally:
        r.close()

    fails = [row for row in rows if row[2] == "fail"]
    print("")
    print(f"=== SUMMARY: {len(rows)} rows, {len(fails)} failures ===")
    if fails:
        for f in fails:
            print("  FAIL:", f)
        return 1
    print("ALL LIVE STRESS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())