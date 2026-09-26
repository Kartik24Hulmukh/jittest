# September 26 continuation — NO_GO

Resumed exactly at f7788e6 / PR #224. The supplied handoff was not treated as
verification: GitHub reported lint and aggregate CI failure on that SHA.

## Frozen five-risk premortem
Before touching source, `frozen-gates.json` fixed zero owned-resource leaks,
zero panics, strict <200ms recovery, 100 real process journeys, 100 workers,
and no merge without all CI and independent launch gates passing.

1. JIT lifetime race: successful parent exit strands descendants.
2. Starvation: capture=False reads block and stop draining at the cap.
3. Nondeterministic readiness drift: preserve seed 20260919 and existing swarm.
4. Disk exhaustion and spawn-failure tempfile leaks in file capture.
5. Windows helper retention and lack of OS-owned descendant containment.

## Implemented partial repair (two proc remediation cycles)
- ExitStack/TemporaryFile own descriptors and remove spawn-error capture leaks.
- POSIX session kill now executes after successful parent exits and cancellation.
- capture=False uses DEVNULL, eliminating its blocking pipe-reader architecture.
- Retention capped at 2MiB per stream; permanent real-process cap tests added.
- Reject NaN/infinite/negative timeout/grace budgets before spawn.
- Completed Windows taskkill helpers are pruned during operation.
- Recovery timestamps include capture reading, decoding and file closure.
- Removed unsupported guarantees of deterministic sub-200ms recovery.
- Launch command now refuses on #223/#225 even if focused tests pass. Removed
  closed #198 from GA blockers; #73 remains open.
- No new runtime dependencies. Existing CPython/uv/pytest/ruff/mypy integrations
  logged in repos.md. No mocks, sleeps or threshold relaxation added.

## Real engine abuse — not probe-only requests
All rows run 100 parent-exit plus 100 timeout journeys, 100 workers. Parent
scripts create real inherited-handle descendants; harness cleanup is explicitly
separate from supervisor reclamation. Seed applies to probe persona ordering;
process scheduling is naturally nondeterministic.

| Run | Cleanup P50/P95/P99/max ms | >=200ms | live descendants | spawn temp leaks |
|---|---|---:|---:|---:|
| Baseline f7788e6, Python 3.14 | 99.421/202.040/294.979/295.448 | 9 | 100 | 2 |
| Cycle 1 | 6.168/131.016/198.962/202.794 | 1 | 0 | 0 |
| Post-change concurrent load | 3.092/195.453/198.816/199.038 | 0 | 0 | 0 |
| Python 3.13 repeat 1 | 3.690/194.345/197.676/202.535 | 1 | 0 | 0 |
| Python 3.13 repeat 2 | 6.644/194.492/200.520/294.038 | 2 | 0 | 0 |
| Python 3.13 repeat 3 | 2.274/198.685/397.555/493.340 | 5 | 0 | 0 |

All completed engine samples show zero thread/FD delta and a 2MiB retained
capture. This does NOT prove zero memory/disk/zombie leaks. Live descendant
checks treat zombie processes separately from executing children. POSIX process
groups cannot contain deliberately detached sessions. Windows job containment
has not been implemented or verified. Temporary-file disk usage remains unbounded.

## Probe swarm under competing load
120 journeys / 20 kinds / 100 workers / 1,000 requests, seed 20260919:
P50/P95/P99 **317.869/476.619/490.899ms**, throughput **276.7rps**,
RSS **29.5–52.6MiB**, traced peak **9.36MiB**, probe recovery **1.212ms**,
zero unhandled thread panics, unexpected statuses or registry drift.
These are probe-plane metrics, not engine throughput or a 100x throughput proof.
Existing observability suite also passes; no new telemetry backend is claimed.

## Remaining merge/launch blockers
- #223: repeated real 100-process recovery still violates strict <200ms under load.
  Requires bounded admission/deadline-aware scheduling with explicit overload
  semantics, not a sleep or narrower timer. Failures retained, not rerun away.
- #225: OS-owned Windows containment, detached POSIX descendants, bounded disk
  capture, and verified complete reclamation remain unresolved.
- #73: real catch-rate, false-positive rate and cost evidence are missing.
  No price, traction, customer endorsement or launch-readiness claim invented.
- New cross-platform GitHub CI must pass on the pushed SHA. No merge while any
  independent frozen gate fails, even if ordinary CI turns green.

Checkpoint and escalation, not launch approval. Source repair stopped after two
cycles, below the five-cycle limit. Subsequent repetitions are measurements of
the same source, not additional fixes. No branch other than
`harden/jittest-v1-launch` was created or modified.

## Validation
- Python 3.13.5 full pytest: **1230 passed, 8 skipped, 210 subtests**, 89.07s.
- Process + persona targeted tests: **20 passed, 8 subtests**.
- Launch-gate unit tests: **31 passed, 49 subtests**.
- Observability suite: **28 passed**.
- ruff: all checks passed; mypy: no issues in 51 source files.
- Launch command: **NO_GO**, specifically runtime_blockers, not a test failure.
- Baseline Python 3.14 full suite: 1230 passed, 1 skipped, 202 subtests.
- Python 3.14 post-change full suite: **1235 passed, 1 skipped, 210 subtests**, 215.42s.
- Cross-platform CI on the new commit is pending at checkpoint; no all-green claim is made.

## Concurrent remote update reconciled
Initial push was safely rejected (no force). Fetched upstream `178eefe`
(lint-only) and `f3bca6b` (capture-cap tests), rebased this slice, retained both
new upstream tests, and reran targeted process/launch tests: **46 passed,
57 subtests**; ruff clean. Full-suite counts above predate this rebase.
