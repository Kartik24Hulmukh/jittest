# Continuous-run memory soak — closeout (2026-09-16 launch window)

Closes the `long memory soak` gap left open by the 0.4.1 hardening closeout
(#204). Burst concurrency was already covered by `scripts/bench_refusal_history.py`;
nothing proved the pipeline is leak-free under *continuous* operation.

## Harness
`scripts/soak_memory.py` — fixed seed `20260916`, 40 segments x 2,500 ops =
**100,000 operations** of the detached refusal-phase-history + canonical-JSON
path. Per-segment RSS **floors** are fitted with ordinary least squares
(KiB retained per 1,000 ops); floors are used because allocator high-water
marks are noisy while floors track *retained* memory. Segment 0 is dropped
from the fit (interpreter/import warmup). Fail threshold: 1.0 KiB / 1k ops
(~860 MiB/day at 10k ops/s — fatal for a long-lived SaaS worker).

## Result (Linux 6.8, CPython 3.14.6)

| Metric | Value |
|---|---:|
| Total ops | 100,000 |
| Errors / unhandled panics | 0 |
| Distinct digests | 1 (deterministic) |
| RSS floor first -> last segment | 38,864 -> 39,020 KiB |
| Leak slope | ~0.0 KiB / 1k ops (limit 1.0) |
| `leak_suspected` | false |
| Throughput | ~22,100 ops/s |
| Latency p50 / p95 / p99 (median of per-segment percentiles) | ~0.020 / ~0.030 / ~0.040 ms |

Machine-readable evidence: `docs/evidence/memory-soak-20260916.json`
(includes the full 40-point `segment_floor_series`).

## Real defect found and fixed in the harness
The first soak run reported **41 KiB / 1k ops** growth (39.0 -> 42.9 MiB over
100k ops) and correctly failed with `leak_suspected: true`. Root cause was in
the measurement code, not the product: the harness accumulated 100,000 latency
floats (~4 MiB) in a live list, which the RSS floor fit then read as product
leakage. Fixed by computing **per-segment percentiles** and discarding the
sample list each segment. Re-run: flat RSS, slope ~0. This is exactly the
class of false positive a leak gate must not ship with.

## Scope honesty (unchanged GA posture)
- Single process, synthetic metadata pipeline. **Not** a container-chaos or
  full-verify capacity claim; no Docker/Podman daemon available here.
- 100k ops is a ~4.5 s soak on this host, not a multi-hour production soak;
  it bounds *per-op* retention, not fragmentation over days.
- `ga_ready` remains **false**. Still open: trusted target-runtime inventory,
  container kill/IO-drop chaos, manifest/rerun semantics coverage, real
  catch-rate / FPR / USD-per-PR evaluation. No tag, no PyPI publication.
- The token pasted into the task prompt is exposed and should be rotated.

## Tests
`tests/test_memory_soak.py` — 6 cases: short-soak determinism, seed
reproducibility, synthetic-leak detector sensitivity (10 KiB/1k ops caught),
flat/degenerate slope safety, scope-note honesty, CLI JSON evidence export.
All green. Related suites re-run green: `test_stress_100x`,
`test_chaos_resilience`, `test_prod_observability`, `test_phase_boundaries`,
`test_anti_fabrication_lint` (57 passed total in the focused run).
