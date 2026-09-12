# JitTest continuation: hardening evidence and release gate

Branch: `harden/jittest-prod` · PR: https://github.com/Kartik24Hulmukh/jittest/pull/186

**Not yet approved for release.** Full local suites and new-head CI must finish; live-daemon E2E is not available here. This report supersedes overclaims in the earlier delivery summary. No new release or tag was created.

## Post-mortem: observed versus reported

The supplied `jittest_hardening_delivery.md` reports version drift (0.4.0 vs 0.3.5) and a fail-open release `|| true`. Those changes already exist at baseline `648e4fa`; the original battle's raw log was not supplied. They are not presented as newly repaired here.

A fresh authenticated download of GitHub job **103625994598**, run **34720740491**, established an additional exact failure at that baseline: `python -m unittest discover` ran 777 tests in 57.175 s and failed with **two import errors**, `tests.test_chaos_resilience` and `tests.test_stress_100x`, both `ModuleNotFoundError: No module named 'pytest'`. This is a dependency-free discovery contract violation, not a demonstrated deadlock. Existing negative-test annotations are not independently CI defects. The fix follows the repository's existing explicit `unittest.SkipTest` convention for pytest-only modules; the subsequent pytest lane still runs all those tests. New boundary tests use stdlib unittest and run in both lanes.

Fresh baseline fault injection also reproduced:
- Initial digest inspection leaks `ConnectionError`; malformed plan/missing file leak `KeyError`, `TypeError`, and `FileNotFoundError` rather than the API's typed refusal.
- Destroy failures escape as raw exceptions; in a dual-fault case they mask the primary `wheelhouse_empty` refusal.
- Wheel hashing calls `Path.read_bytes()`, retaining a full artifact per concurrent worker. A 32 MiB wheel at 32 workers produces roughly 1 GiB of traced live allocations.

The baseline regression run reports 9 failures (including unittest subtest failures). All corresponding candidate regressions pass. No new deadlock or state-corruption event was observed. Existing CI documents a descendant inheriting the runner's stdout pipe and preventing EOF; its guards are 60 s per test, 900 s external process cap with 30 s kill grace, and 25 min job timeout. The earlier 45 s execution-tool limit is not an application latency threshold. Local jobs run detached with file logs and explicit deadlines to avoid mistaking tool timeout for suite outcome.

## Architectural changes

1. One ownership-scoped container context handles exactly-once cleanup after successful acquisition. A primary failure stays primary, with cleanup failure recorded as an exception note. Cleanup-only failure becomes `ProvisioningRefusal` and prevents advancing to phase 2. Exceptions retain causal chains. KeyboardInterrupt/SystemExit are not converted into success or swallowed.
2. Preflight validates serializable plan strings and canonical SHA-256 syntax and translates ordinary boundary failures into typed refusals before allocation. Both chaos tests now require typed refusal, not a broad tuple that accepts the original bug.
3. Streaming `hashlib.file_digest` removes whole-wheel allocation; canonical manifest hashes remain identical to the baseline for the same workload.
4. No host fallback, blind cleanup retry, or gate bypass was introduced. A destroy error means cleanup is **unresolved**, not “zero leaked containers.”

## Stress and adversarial coverage

- Existing 200-job provisioning, 200-job refusal storm, 50-job between-phase digest drift, 400 integrity records, 100 output scans, and 200 mixed honest/adversarial jobs retained.
- Added 500 seeded shuffled jobs at 32 workers, collected in completion order then normalized by job ID; exact accept/refuse, per-engine state isolation, deterministic manifests and honest unresolved-cleanup invariants asserted.
- New fault sweep covers both preflight inspection calls, invalid plans, missing requirements, both cleanup phases, simultaneous primary/cleanup failure, exactly-once healthy cleanup and streaming allocation behavior.
- Focused run: **50 passed, 69 subtests passed** on local Python 3.14.6. These are fake-engine/contract tests, not proof of real container isolation.

## Benchmark deltas

Three repetitions per variant and workload; alternating baseline/candidate order; same host, Python 3.14.6, seed 186, 32 workers, 10 warmups. 4 KiB workload: 1,000 jobs/run. 32 MiB workload: 64 jobs/run. Table shows medians of per-run measurements, not pooled percentiles. `tracemalloc` was enabled for both; latency and throughput are instrumented. Other local suites were running, so these are directional microbenchmarks, **not an SLO or isolated performance certification**. Traced memory is not RSS, cgroup usage, or a whole-system ceiling. Queue-inclusive latency begins at submission; service latency begins in the worker. Raw JSON and reproducible harness are committed.

| Wheel size | Metric | Baseline 648e4fa | Candidate | Delta |
|---|---|---:|---:|---:|
| 4 KiB | service P50 ms | 15.129 | 18.177 | +20.1% |
| 4 KiB | service P95 ms | 70.803 | 81.938 | +15.7% |
| 4 KiB | service P99 ms | 79.263 | 90.507 | +14.2% |
| 4 KiB | queue-inclusive P50 ms | 304.150 | 484.122 | +59.2% |
| 4 KiB | queue-inclusive P95 ms | 697.873 | 903.849 | +29.5% |
| 4 KiB | queue-inclusive P99 ms | 712.179 | 920.123 | +29.2% |
| 4 KiB | throughput jobs/s | 1197.023 | 884.250 | -26.1% |
| 4 KiB | peak traced MiB | 3.328 | 6.553 | +96.9% |
| 32768 KiB | service P50 ms | 900.018 | 503.465 | -44.1% |
| 32768 KiB | service P95 ms | 1108.451 | 596.747 | -46.2% |
| 32768 KiB | service P99 ms | 1271.215 | 600.621 | -52.8% |
| 32768 KiB | queue-inclusive P50 ms | 1247.154 | 748.691 | -40.0% |
| 32768 KiB | queue-inclusive P95 ms | 1899.713 | 1005.045 | -47.1% |
| 32768 KiB | queue-inclusive P99 ms | 1908.885 | 1005.776 | -47.3% |
| 32768 KiB | throughput jobs/s | 30.571 | 57.832 | +89.2% |
| 32768 KiB | peak traced MiB | 1024.343 | 12.389 | -98.8% |

Small-wheel overhead is reported, not hidden: streaming and lifecycle safety have a cost. Large-wheel throughput and traced memory improve substantially. There is no universal memory ceiling claim: path enumeration, manifest count, requirements size and scheduler backlog still scale with input.

Reproduce from the repository, choosing `PYTHONPATH` for the revision under test:

```sh
PYTHONPATH=src python scripts/bench_provision.py --jobs 1000 --workers 32 --wheel-bytes 4096 --seed 186 --output small.json
PYTHONPATH=src python scripts/bench_provision.py --jobs 64 --workers 32 --wheel-bytes 33554432 --seed 186 --output large.json
python -m pytest tests/test_provision_boundaries.py tests/test_stress_100x.py tests/test_chaos_resilience.py tests/test_version_drift.py tests/test_hardening.py tests/test_module_entrypoint.py
PYTHONPATH=src python -S -m unittest discover -s tests -p 'test_*.py' -t . -v
```

## Premortem / remaining production risks

| Scenario | Current behavior / required follow-up |
|---|---|
| Engine creates remotely then errors before returning ID | Ownership unknown; requires engine-side idempotency keys, labels and reconciliation; cannot claim no leak. |
| Engine destroy fails or hangs | Typed refusal on error; no in-process thread timeout can safely cancel a remote operation. Engine deadline and external reaper required. |
| Wheelhouse mutates after freeze / tag changes after inspection | Existing between-phase digest check catches tested drift, not all TOCTOU. Immutable digest execution and immutable wheelhouse snapshot needed at real adapter boundary. |
| Oversized artifact count or requirements | Streaming bounds per-artifact hashing buffer, not total metadata/backlog. Admission limits and measured RSS/cgroup caps remain open. |
| Adversarial pip directives / nested includes | Existing VCS/local-path corpus is not a complete pip parser. Full allowlist/recursive policy validation remains a separate security gate. |
| Cross-platform process behavior | Linux local Python 3.14 is outside the 3.11–3.13 release matrix; latest-head CI remains authoritative. |

## Release checklist (fail closed)

- [x] Verify baseline CI failure from actual logs; retain exact identifiers.
- [x] Reproduce boundary bugs before remediation; focused regressions green.
- [x] Preserve primary errors and report unresolved cleanup honestly.
- [x] Seeded out-of-order fault sweep and raw latency/throughput/memory measurements.
- [ ] Full candidate unit/integration/E2E gates green; no failure or timeout waived.
- [ ] Latest-head Linux/macOS/Windows Python 3.11–3.13 CI green.
- [ ] Registry-live real-daemon E2E evidence reviewed; Docker/Podman absent locally.
- [ ] Confirm full pip-policy and immutable-artifact threat model before production certification.
- [ ] Review earlier recommendation to yank invalid 0.4.0 and publish 0.4.1 without tag reuse; this run did not execute it.
- [ ] Rotate the credential exposed in task history. Authentication uses only `GIT_AUTH_TOKEN`, never project files or remote URLs.
