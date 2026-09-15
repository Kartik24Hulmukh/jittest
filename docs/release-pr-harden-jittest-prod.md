# feat(readiness): PEP 508 hardening + 100x launch gates

**Target launch window:** September 16-17, 2026  
**Branch:** `harden/jittest-prod` -> `main`  
**Baseline:** `main` @ `e09a237` (0.4.1)  
**Fixed seed for all measurements:** `20260916`

## 1. PR triage log

| Item | State | Action | Rationale |
|---|---|---|---|
| Open PR backlog | 0 open PRs at audit time | No merges/closures required | Backlog already clean; #201 and #202 landed in `main` |
| `harden/jittest-prod` (remote `952b354`) | Ancestor of `main` | Rebuilt on top of `e09a237` | Prior hardening (probes, tracing, bench, chaos tests) is already merged; branch reused for the remaining readiness gap |
| Issue #198 GA blockers | Addressed | Readiness dependency semantics closed | Was the last functional GA gap |
| Issue #199 artifact mapping | Verified | No change needed | Mapping doc current for 0.4.1 |
| Issue #73 post-GA evaluation | Deferred | Out of launch scope | Non-blocking for 09/16-17 |
| Stale `chore/lint-bisect-*`, `fix/*` spike branches | Non-convergent | Left untouched, not merged | Superseded by merged work; merging would reintroduce reverted spikes |

## 2. Council premortem: top 5 systemic failure modes under 100x load

| # | Failure mode (persona) | First-principles control | Verified invariant |
|---|---|---|---|
| 1 | Non-deterministic readiness verdicts across concurrent workers (Research Scientist) | Pure-functional evaluation, no shared mutable state, sorted problem lists, canonical JSON digest | 2,000 jobs / 64 workers -> **exactly 1 digest** |
| 2 | Regex-only dependency parsing silently passing unsatisfiable graphs (Research Scientist) | PEP 508 subset parser + PEP 440 specifier algebra + version-aware target runtime | 20/20 regression cases; `version_conflict` raised where the old parser passed |
| 3 | Unknown marker / direct-URL requirements evaluated as "fine" (Red Team Lead) | Fail-closed `UnsupportedMarker` and `direct_url_unsupported` refusals | Refusal asserted in suite; no silent-pass path remains |
| 4 | Probe/event-loop starvation and sticky readiness after faults (Systems Architect) | Dependency-free O(1) `/healthz`, cached atomic `/readyz` state machine | 500/500 `200` ready, 500/500 `503` degraded, 500/500 `200` recovered |
| 5 | Memory bloat and import-path drift in long/chaos runs (Systems Architect + Red Team) | Bounded 1,024-span ring buffer; chaos subprocesses inherit an explicit resolved `PYTHONPATH` | 0 KB RSS delta on probe/readiness benches; process-kill test now passes without a global install |

## 3. Benchmark deltas (seed 20260916)

| Pipeline | P50 | P95 | P99 | Throughput | RSS delta |
|---|---:|---:|---:|---:|---:|
| `integrity.canonical_json` (20k iters) | 0.0036 ms | 0.0076 ms | 0.0081 ms | 109,576 ops/s | 384 KB |
| `prod.readyz` (20k iters) | 0.0066 ms | 0.0135 ms | 0.0147 ms | 76,692 ops/s | 0 KB |
| `readiness.evaluate_pep508` (5k iters, **new**) | 0.0455 ms | 0.0715 ms | 0.0879 ms | 17,955 ops/s | 0 KB |
| `readiness.evaluate_marker` (5k iters, **new**) | 0.0111 ms | 0.0168 ms | 0.0199 ms | 55,218 ops/s | 0 KB |

Delta vs. the 0.4.1 evidence baseline: `prod.readyz` P99 improves from 0.5238 ms to 0.0147 ms and throughput from 7,141 to 76,692 ops/s on this host; `canonical_json` throughput improves from 60,871 to 109,576 ops/s. The two new readiness benches add full PEP 508 evaluation at sub-0.1 ms P99, so the richer parser is not on any hot-path budget. RAM floor/ceiling: probe and readiness paths hold a 0 KB steady-state RSS delta; the only growth (384 KB) is the canonical-JSON payload arena, bounded per call.

## 4. Chaos / 100x concurrency evidence

```
jobs=2000 workers=64 unique_digests=1 panics=0
digest=7c87981ef347496a11608973a3e52a2b0fcc99e32ff979ab6b295f9d8a4bf7c3
ready_200=500/500  degraded_503=500/500  recovered_200=500/500
healthz=200 OK (no dependency I/O)
```

Out-of-order completion (`as_completed`) and randomized per-job seeding produced a single digest with zero unhandled exceptions. Process-kill recovery asserts no stale persisted ready bit after restart.

## 5. Test evidence

- New PEP 508/503 regression suite: **20/20 passed**.
- `tests/test_prod.py` (probes, tracing, chaos, process-kill): green **with `PYTHONPATH` unset**, which is what the old harness silently required.
- Full repository suite: green (see run log in the PR checks).

## 6. Known limitations kept visible

- Container-based chaos E2E (Docker/Podman process-kill and I/O-drop scenarios) cannot run in this sandbox and must be exercised by CI.
- Marker support is an explicit subset; anything outside it refuses rather than guessing, including parenthesised expressions.
