# Launch revalidation — September 15, 2026

## Decision: developer-preview scope only; GA blocked

Starting commit: `2ba576231cf296116d02a8551966ead2e19dac54`.
Live GitHub checks: 23 success, 1 expected dogfood skip; zero open PRs at intake.
Live issues: #73, #198, #206; #199 is closed. The launch gate incorrectly
still listed #199; this patch replaces it with #206, without removing GA blocking.

## Attachment integration audit

Both entries in the supplied ZIP were read, including valid verification JSON.
The original Markdown contains a plaintext credential and is deliberately NOT
copied to this repository. Revoke and replace that credential promptly.

| File | SHA-256 |
|---|---|
| jittest-v1-launch-readiness-council-audit.md | f107d3216f4b850566c7d12a75f3e71dffa1cf7bdfb4a0fcf3df67b0d815e023 |
| jittest-launch-gate-verification.json | 307d20cfdaa058ddebbf71b0bda1c1d5af391691410d4bc4d7c31a7c10206888 |

The attached gate digest reproduces at the starting commit. Its benchmark table
(8.4/21.2/54.8 ms, 1,240 ops/s) has no raw data in the ZIP; it is NOT independently
verified. The two earlier reports named inside the audit are not attached.
The audit overstates synthetic metadata/fake-engine tests as production chaos
and sustained 100x capacity. Those claims are not adopted here.

## Council premortem (one agent, four review lenses; not independent agents)

| Failure vector | Lens | Resolution / honest remaining boundary |
|---|---|---|
| False launch approval through truthy receipt flags or empty gate sets | Research scientist | Strict JSON booleans, explicit semantic validity, nonempty gate sets; regressions added |
| Silently omitted suites or skipped tests approving launch | Systems architect | Missing focused files refuse before execution; --skip-tests is diagnostic NO_GO |
| Concurrency races / starvation | Systems architect + chaos | Existing 64-worker 2,000-job invariant passes; additional shuffled 1-vs-100 configured-worker microbenchmark has matching result digest; no full verify capacity claim |
| State drift / memory retention | Research scientist + chaos | Fresh 100,000-op soak: zero errors, one digest, zero RSS-floor growth; no long-duration leak-free guarantee |
| Supply-chain secrets and overstated launch readiness | Founder + chaos | No credential copied; existing environment/receipt boundaries retained; #73/#198/#206 remain open; no automatic GA claim |

## Changes and validation

Six regression tests cover malformed receipt payloads, strict booleans, semantic
refusal exit codes, empty/truthy gate sets, missing suites and skipped tests.
Focused launch/stress/chaos/observability run: 58 passed plus 49 subtests.
Full-suite validation is pending at initial PR creation; merge is conditional.
Two local remediation iterations were used (second corrected lint layout only).
The initial full suite was collected before edits, but was still running during
edits; it is not treated as an immutable full-suite baseline. The completed
baseline gate, benchmark and exploit reproductions were saved before edits.

## Benchmarks and reproducibility

Raw exports are under `docs/evidence/launch-revalidation/`. Fixed seeds reproduce
inputs and result digests, not wall-clock timings. Measurements share a sandbox
with test processes and are not controlled performance comparisons.

| Workload | P50 ms | P95 ms | P99 ms | Throughput ops/s |
|---|---:|---:|---:|---:|
| Baseline canonical JSON | 0.009909 | 0.018269 | 0.021841 | 22657.884 |
| Baseline SHA256 + canonical JSON | 0.010580 | 0.018552 | 0.019744 | 21335.040 |
| Baseline readyz | 0.132482 | 0.168089 | 0.537720 | 4599.017 |
| Shuffled metadata, 1 configured worker | 0.004710 | 0.006970 | 0.009640 | ~49493 |
| Shuffled metadata, 100 configured workers | 0.010480 | 0.014600 | 0.020590 | ~20359 |

The worker comparison changes concurrency, not source version. Service latency
excludes queue delay. Threads are lazily created; 100 configured workers is NOT
proof of 100 simultaneously executing workers. Process RSS high-water in that
comparison was 26,672–30,768 KiB, not a sampled RAM floor/ceiling.
The separate 100k-op soak sampled RSS floors at 38,512 KiB throughout; ceiling
was not exported. Production RAM floor/ceiling and before/after production
latency/throughput deltas remain unmeasured. No performance improvement claimed.

Reproduce from repository root:

```sh
python -m pip install -e '.[dev]'
PYTHONPATH=src python scripts/launch_gate.py --json gate.json
python -m pytest --timeout=60 -o addopts= -q
PYTHONPATH=src python scripts/bench_100x.py --out bench.json
PYTHONPATH=src python scripts/soak_memory.py --out soak.json
```

## Launch and external blockers

No Docker executable is available in this environment, so real container crashes,
socket-drop recovery and dependency-bearing public-path acceptance were not
validated. The fake-engine chaos suite proves refusal contracts only. Do not
infer successful cleanup when destroy itself fails.

OpenTelemetry API/fallback tracing and real /healthz and /readyz implementations
already exist. A host-configured SDK/exporter is still required for exported
OpenTelemetry traces; no collector proof was run here. No mock endpoint added.

#73 needs an owner-approved funded evaluation and real pricing; #198 needs live
pinned-runtime/public-path evidence; #206 needs an authentic run to regenerate
its semantically invalid signed showcase receipt. Do not hand-edit the receipt
or assume an inaccessible signing key is the only blocker.

The user definition of done (all roadmap work, sustained production 100x,
complete real chaos recovery, merged launch-ready GA release) is NOT met.
