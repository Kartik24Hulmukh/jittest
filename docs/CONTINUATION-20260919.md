# jittest continuation — evidence, not launch certification

## Decision
PR #222 contains useful, tested hardening but **unconditional production readiness is not established**. No paid model evaluation or real customer research was performed. Synthetic journeys are not 100 human participants. A failed overloaded recovery run is retained alongside passing runs.

## State and fixes
Audited `main=5821aae`, open PR #222 at `d1f7427`; all four supplied reports were read. The prior local commit did not persist. `repos.md` exists on the PR branch, not main.

1. `5575f76`: reproduced optional Hypothesis decorator import failure before editing; conditionally define the property class, add `python -S` discovery regression, declare Hypothesis in dev extras and install it only after dependency-free CI.
2. `3cd9a0a`: reproduced an unclosed chaos-server listening socket (descriptor 11 instead of -1); explicitly close it after shutdown, with a retained-server regression. Targeted regression failed before and passed after (9 tests).
3. Correct misleading claims: `Popen.wait(timeout)` is not universally event-driven (POSIX CPython may poll internally); fixed seeds stabilize inputs, not timing/RSS. No runtime dependency was added.

## Five-point premortem
| Failure mode | Evidence / disposition |
|---|---|
| Optional dependency disables discovery | Baseline import error frozen; no-site-packages regression now passes |
| JIT/process timeout race and scheduler starvation | Typed timeout tests pass in isolated final run; overloaded run had two >200 ms timeout overshoots — unresolved capacity boundary |
| Readiness state drift | Concurrent writers/readers and final swarm: no registry drift |
| Resource exhaustion / leaks | Listener leak reproduced/fixed; 100,000 metadata-op soak found no leak above configured slope/noise thresholds; not proof of zero leaks everywhere |
| Sandbox trust or observability failure | Real Docker Option C, cleanup, phase-boundary and registry artifacts verified; chaos logs: 1,562 JSON lines, zero invalid JSON or secret/traceback leaks |

## Verification
- Python 3.13.5 Linux, `PYTHONHASHSEED=0`.
- Final pytest with Hypothesis, cryptography, jsonschema and real OpenTelemetry SDK: **1220 passed, 1 skipped, 202 subtests passed**. The skip is local Docker cleanup; the exact test ran remotely without skip.
- Dependency-free `python -S -m unittest discover`: see `validation.json` for exact counts; exit 0.
- Full ruff and mypy gates: exit 0 (51 source files type-checked).
- `scripts/bench_100x.py`: 2,000 jobs / 64 workers, one digest, 2,000 closed spans, zero panics. This is not 100x full differential pipeline capacity.
- 100,000 metadata operations: deterministic digest, no errors, no suspected leak under the harness threshold.

## Measured load (not performance improvement claims)
All rows use synthetic probe-plane traffic, seed 20260919. Burst comparisons were not on an otherwise idle dedicated machine; the 100-worker rows are repeated capacity observations, not controlled speedup evidence.

| Run | Requests | Workers | P50 / P95 / P99 ms | Requests/s | Recovery ms | RSS floor / ceiling MiB |
|---|---:|---:|---|---:|---:|---|
| Serial reference | 10000 | 1 | 0.564 / 0.774 / 0.944 | 1571.5 | 1.042 | 25.5 / 63.7 |
| Load A | 10000 | 100 | 74.693 / 130.755 / 200.425 | 1176.8 | 1.001 | 26.3 / 78.1 |
| Load B (contended host) | 10000 | 100 | 484.517 / 598.121 / 994.182 | 214.4 | 1.434 | 26.2 / 78.1 |
| Load C | 10000 | 100 | 71.799 / 80.269 / 131.081 | 1352.4 | 1.083 | 26.1 / 78.3 |
| Final isolated swarm | 1000 | 100 | 67.025 / 72.112 / 80.265 | 1398.3 | 0.929 | 26.2 / 47.7 |

All three 10,000-request runs passed the existing harness contract. The separate `swarm.json` overlapping other suites **failed** two hard-timeout persona checks; probe recovery itself was 1.228 ms. No SLO was relaxed. Final isolated swarm passed, but does not erase the overloaded failure. Launch requires a dedicated capacity/recovery investigation.

Compared with the historical PR artifact (different host), final 1,000-request P50/P95/P99 changed from 81.7/91.5/98.4 to 67.025/72.112/80.265 ms; throughput 1140.6 to 1398.3 rps; RSS 29.6/51.8 to 26.2/47.7 MiB. These are **observational deltas, not attributable optimization gains**.

Separate chaos scenario matrix: 100 distinct persona/network/header combinations, 2,000 requests, 2440.2 rps, P50/P95/P99 28.238/101.348/148.505 ms, recovery 29.624 ms, zero unexpected transport errors or tracebacks.

## Real-daemon blocker advanced
Dispatched and downloaded https://github.com/Kartik24Hulmukh/jittest/actions/runs/35454063661 on code SHA `5575f762fa0eb814361616d533ba5bd0926ca2fd`:
- Option C: RUN, passed, two container tests green.
- Descendant cleanup JUnit: 1 test, 0 skips/errors/failures.
- Phase boundaries: RUN, proven_catch, base PASS / head FAIL / rerun FAIL; signature valid, tamper rejected, base-only violation refused.
- Registry: RUN, digest verified against RepoDigests.

Artifacts are copied unmodified in this evidence directory. Later functional changes only affect the chaos test harness, not sandbox production code. Issue #73 was updated with this evidence; it was not closed.

## Tool integration log
From `repos.md`: CPython subprocess/unittest, pytest/xdist/timeout, Hypothesis, ruff, mypy, optional OpenTelemetry SDK, cryptography, Docker via the existing GitHub workflow. Optional jsonschema exercised receipt contracts already present in the repository. No external runtime service or production dependency added; no locust/vegeta deployment claimed.

## Remaining launch gates
1. Explain and eliminate hard-timeout recovery overshoot under simultaneous heavy workloads; preserve <200 ms target.
2. Dedicated sustained full-pipeline capacity test (100 workers is not 100x measured production throughput).
3. Real bug catch rate, false-positive rate and verified dollar cost; provider/model is unpriced, so do not equate request ceiling with USD ceiling. Evaluation secrets/variable names exist; values were not copied. Paid workflow was not dispatched.
4. Real maintainer feedback and adoption evidence; no traction claim from simulated personas.
5. Finish required GitHub CI and merge only green code; never bypass protection. This report is pre-merge evidence, not a merge receipt.
6. Rotate the task-exposed PAT; it was used only for authorized GitHub operations and is not committed.

Convergence: one red/green repair cycle per discovered code defect; one controlled retest of the overloaded stress failure, explicitly unresolved rather than silently marked fixed.
