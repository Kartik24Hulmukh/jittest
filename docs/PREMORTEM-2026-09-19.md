# Premortem 2026-09-19 - 100-persona human swarm + 100x concurrency (launch window 17-18 Sep)

Council: Research Lead (determinism) | Principal Architect (runtime) | Red Team Lead (chaos) | 100-human user swarm (UX/edge).
Method: assume the launch failed on 18 Sep; write the five most likely causes; prove each one wrong with a frozen artefact.

## Frozen baseline (before touching `src/`)

`python -m pytest tests -n 8 --timeout 180` -> **1211 passed, 1 skipped, 202 subtests passed, 0 failed (177 s)**.
`grep -rn time.sleep src/` -> `proc.py:133` (20 ms poll loop), `llm.py:240` (request pacing, injectable).

## The five failure modes

| # | Owner | Failure mode | Native resolution | Evidence |
|---|-------|--------------|-------------------|----------|
| 1 | Architect | **JIT race / dead time in the process supervisor**: `run_bounded` polled `proc.poll()` every 20 ms, adding up to 20 ms latency per exit and a scheduler tick under 100x load | `Popen.wait(timeout=)` - kernel-level `waitpid`; the child exit wakes the caller immediately, timeouts raise `TimeoutExpired` and the tree is killed | `tests/test_persona_swarm_100x.py::test_run_bounded_timeout_recovers_within_200ms` (overshoot < 200 ms), `::test_run_bounded_has_no_polling_sleep`; `tests/test_proc_bounded.py` unchanged and green |
| 2 | Architect | **Thread starvation** in the probe server when 100 humans connect at once, some never finishing their request (slowloris) or vanishing (RST) | `_Handler.timeout = 10 s`, `_CLIENT_GONE` handling in `handle/finish/_respond`, `ThreadingHTTPServer` | swarm: `slow_half_request`, `rapid_cancel`, `network_dropout_rst` personas at 100 workers -> 0 panics; recovery request answered in **1.1 ms** |
| 3 | Research | **Non-deterministic state drift**: conflicting writers mutating the readiness registry while readers hit `/readyz`; results that differ run to run | `_REGISTRY_LOCK` (RLock) around register/unregister; swarm seeds every persona from `seed*1000+idx`, shuffles order deterministically, runs under `PYTHONHASHSEED=0` | `registry_drift: false` after 20 conflicting writers x 20 cycles; `test_swarm_report_is_deterministic_for_a_fixed_seed` |
| 4 | Red Team | **Erratic payload shapes crash or leak**: garbage bytes, 16 KB headers, unicode paths, HTTP/1.0, `OPTIONS`, `//healthz`, pipelined keep-alive | JSON-only `send_error`, 405 with `Allow`, 404 for unmatched, HEAD = GET headers without body | 200-example Hypothesis property (`derandomize=True`) on `ProbeApp`; 20 persona kinds x 120 journeys, all within contract status sets; `tracemalloc` peak 10.8 MiB, RSS ceiling 51.8 MiB |
| 5 | Swarm | **Malformed test scripts / hard timeouts treated as engine panics** | `run_bounded` returns a `CompletedProcess` for a `SyntaxError` child and raises a typed `TimeoutExpired` with partial output for hangs | `malformed_script` and `hard_timeout` personas; `test_run_bounded_malformed_script_is_a_result_not_a_panic` |

## Benchmark deltas (fixed seed 20260919, 100 workers, 1000-request burst, 120 personas)

Source: `docs/evidence/persona-swarm-20260919.json` (regenerate with the command in `scripts/persona_swarm_100x.py`).

| Metric | Value |
|--------|-------|
| P50 / P95 / P99 latency (`/healthz`, 100 concurrent clients) | 81.7 / 91.5 / 98.4 ms |
| Throughput at 100x | 1140.6 rps (1000 requests in 0.88 s, single-process stdlib server) |
| Recovery after chaos (first clean `/readyz`) | 1.1 ms (< 200 ms SLO) |
| RSS floor / ceiling | 29.6 MiB / 51.8 MiB |
| tracemalloc peak | 10.8 MiB |
| Unhandled thread panics | 0 |
| Persona contract violations | 0 / 120 |
| `run_bounded` timeout overshoot | < 200 ms (was up to +20 ms poll latency, now kernel wakeup) |

## Convergence log

| Module | Cycles used (max 5) | Outcome |
|--------|---------------------|---------|
| `scripts/persona_swarm_100x.py` | 2 (percentile helper for N<100; ruff import order) | green |
| `tests/test_persona_swarm_100x.py` | 1 (HEAD semantics: Content-Length without body is correct per RFC 9110) | green |
| `src/jittest/proc.py` | 1 | green |

No module reached the convergence limit; no blockers escalated.
