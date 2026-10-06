#!/usr/bin/env python3
"""Deterministic resilience evidence for the Melious router. No network, no spend.

Every scenario runs against a scripted in-process transport, so the evidence is
reproducible offline and costs nothing. Scenarios cover the launch contract:
token-budget ceilings refuse before any request is sent, chain failover
completes well under 200 ms, 429/5xx circuits are bounded and typed, read
timeouts cannot hang past the deadline, and account-scoped refusals (401
auth, 402 billing) never retry or fail over.

Run: python3 scripts/melious_resilience.py --out docs/evidence/melious-resilience-<date>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from jittest.melious import (  # noqa: E402
    AuthenticationError,
    DeadlineExceeded,
    InsufficientCreditsError,
    MeliousRouter,
    TransportError,
)

FAILOVER_BAR_SECONDS = 0.2


def _completion_payload(model: str) -> dict:
    return {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "model": model,
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "billing_cost": {"paid_with": "credits", "credits": "0.000001"},
    }


def _router(handler, **kwargs) -> tuple[MeliousRouter, list[dict]]:
    """Router over a scripted transport; returns (router, request_log)."""
    import httpx

    log: list[dict] = []

    def wrapped(request):
        log.append({"model": (request.content and json.loads(request.content).get("model"))
                    if request.url.path.endswith("/chat/completions") else None,
                    "path": request.url.path, "t": time.perf_counter()})
        return handler(request)

    router = MeliousRouter(api_key="test-key-not-a-secret",
                           transport=httpx.MockTransport(wrapped), **kwargs)
    return router, log


def _run(name, fn) -> dict:
    started = time.perf_counter()
    try:
        detail = fn()
        status = "ok"
    except AssertionError as exc:
        status, detail = "failed", f"assertion: {exc}"
    except Exception as exc:  # unexpected exception type = failed evidence
        status, detail = "failed", f"unexpected {type(exc).__name__}: {exc}"
    return {"case": name, "status": status,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "detail": detail}


def scenario_token_ceiling() -> str:
    import httpx
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=_completion_payload("glm-5.3"))

    router, log = _router(handler)
    with router:
        try:
            router.complete("glm-5.3", "x", max_tokens=65537, deadline=5)
            raise AssertionError("ceiling breach was not refused")
        except ValueError:
            pass
    assert not sent and not log, "a request was sent despite the ceiling refusal"
    return "max_tokens=65537 refused pre-network; 0 requests sent"


def scenario_failover_latency() -> str:
    import httpx

    def handler(request):
        model = json.loads(request.content)["model"]
        if model == "glm-4.5":
            return httpx.Response(404, json={"error": "unknown model"})
        return httpx.Response(200, json=_completion_payload(model))

    router, log = _router(handler)
    with router:
        t0 = time.perf_counter()
        result = router.complete("glm-4.5", "x", deadline=10, max_tokens=16,
                                 truncation_escalation=False)
        failover_ms = (time.perf_counter() - t0) * 1000
    assert result.model == "glm-5.3", f"expected failover to glm-5.3, got {result.model}"
    assert failover_ms < FAILOVER_BAR_SECONDS * 1000, f"failover {failover_ms:.1f}ms >= 200ms bar"
    return (f"glm-4.5 HTTP 404 -> glm-5.3 answered in {failover_ms:.3f} ms "
            f"(bar: <{FAILOVER_BAR_SECONDS * 1000:.0f} ms), requests={len(log)}")


def scenario_circuit_429() -> str:
    import httpx

    def handler(request):
        return httpx.Response(429, json={"error": "rate limited"})

    router, log = _router(handler)
    with router:
        t0 = time.perf_counter()
        try:
            router.complete("glm-5.3", "x", deadline=3.0, max_tokens=16)
            raise AssertionError("429 storm was not bounded")
        except DeadlineExceeded:
            elapsed = time.perf_counter() - t0
    assert elapsed < 4.0, f"429 circuit exceeded deadline slack: {elapsed:.2f}s"
    assert len(log) >= 2, "expected bounded retries before giving up"
    return f"pure-429 storm bounded by deadline in {elapsed:.2f}s after {len(log)} attempts"


def scenario_circuit_5xx() -> str:
    import httpx

    def handler(request):
        return httpx.Response(503, json={"error": "unavailable"})

    router, log = _router(handler)
    with router:
        t0 = time.perf_counter()
        try:
            router.complete("glm-5.3", "x", deadline=30.0, max_tokens=16)
            raise AssertionError("5xx storm was not bounded")
        except TransportError as exc:
            elapsed = time.perf_counter() - t0
            assert "bounded retries" in str(exc), f"wrong error: {exc}"
    assert len(log) == 3, f"expected exactly 3 attempts, got {len(log)}"
    return f"pure-503 storm refused after exactly 3 attempts in {elapsed:.2f}s"


def scenario_read_timeout_no_hang() -> str:
    """Two-part check. (a) The router must hand httpx a read timeout derived
    from the caller's deadline (visible in request extensions). (b) A socket
    read timeout must become a typed error immediately, with no hang and no
    retry storm. (A scripted transport cannot be interrupted mid-sleep, so
    raising ReadTimeout is the faithful simulation of the socket cutoff.)"""
    import httpx

    seen: dict = {}

    def handler(request):
        seen.update(request.extensions.get("timeout", {}))
        raise httpx.ReadTimeout("simulated socket read timeout", request=request)

    router, log = _router(handler)
    with router:
        t0 = time.perf_counter()
        try:
            router.complete("glm-5.3", "x", deadline=0.5, max_tokens=16)
            raise AssertionError("read timeout was not surfaced")
        except (DeadlineExceeded, TransportError):
            elapsed = time.perf_counter() - t0
    read_timeout = seen.get("read")
    assert read_timeout is not None and read_timeout <= 0.5, (
        f"router did not bound the httpx read timeout by the deadline: {seen}")
    assert elapsed < 1.0, f"read timeout handling took {elapsed:.2f}s"
    return (f"httpx read timeout pinned to {read_timeout:.3f}s by the 0.5s deadline; "
            f"ReadTimeout surfaced as a typed error in {elapsed * 1000:.1f} ms")


def scenario_auth_no_retry() -> str:
    import httpx

    def handler(request):
        return httpx.Response(401, json={"error": "unauthorized"})

    router, log = _router(handler)
    with router:
        try:
            router.complete("glm-5.3", "x", deadline=10, max_tokens=16)
            raise AssertionError("401 was not surfaced as AuthenticationError")
        except AuthenticationError:
            pass
    assert len(log) == 1, f"auth refusal must not retry; got {len(log)} requests"
    return "401 surfaced as AuthenticationError after exactly 1 request (no retry)"


def scenario_billing_no_failover() -> str:
    import httpx

    def handler(request):
        return httpx.Response(402, json={"error": "insufficient credits"})

    router, log = _router(handler)
    with router:
        try:
            router.complete("glm-4.5", "x", deadline=10, max_tokens=16)
            raise AssertionError("402 was not surfaced as InsufficientCreditsError")
        except InsufficientCreditsError:
            pass
    assert len(log) == 1, (f"billing refusal is account-scoped and must not fail over "
                           f"or retry; got {len(log)} requests")
    return "402 surfaced as InsufficientCreditsError after exactly 1 request (no failover)"


SCENARIOS = [
    ("token_ceiling", scenario_token_ceiling),
    ("failover_latency", scenario_failover_latency),
    ("circuit_429", scenario_circuit_429),
    ("circuit_5xx", scenario_circuit_5xx),
    ("read_timeout_no_hang", scenario_read_timeout_no_hang),
    ("auth_no_retry", scenario_auth_no_retry),
    ("billing_no_failover", scenario_billing_no_failover),
]


def run_all() -> dict:
    rows = [_run(name, fn) for name, fn in SCENARIOS]
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    diff = subprocess.check_output(["git", "diff", "HEAD"])
    failed = sum(r["status"] != "ok" for r in rows)
    return {"sha": sha, "working_diff_sha256": hashlib.sha256(diff).hexdigest(),
            "evidence_kind": "scripted-transport resilience; no network, no spend",
            "failover_bar_seconds": FAILOVER_BAR_SECONDS,
            "failed_checks": failed, "passed": failed == 0, "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, help="write evidence JSON here (default stdout)")
    args = ap.parse_args(argv)
    evidence = run_all()
    text = json.dumps(evidence, indent=2) + "\n"
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
