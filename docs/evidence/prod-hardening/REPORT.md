# Production hardening increment — 2026-09-13

## Decision: bounded increment, NOT GA certification

The supplied `jittest-release-pr.md` is not execution evidence. Its claims of
all tests passing, completed push/PR, real tracing, zero latency variance, and
no memory leaks were not substantiated by logs or real timing measurements.
Canonical output is not latency determinism; serialization is not a memory
bound. This report supersedes those claims. No token is stored in the repo.

## PR triage and baseline (before source edits)

- GitHub API: **zero open PRs**. No PR required merging or closing. Recent 100
  closed PR metadata captured in `triage.json`; historical PRs were NOT all
  technically re-reviewed. At audit time harden/jittest-prod was an ancestor of main. A concurrent
  writer subsequently published PR #201; its commits were fetched and merged
  without force-push or discarded work. See reconciliation below.
- Baseline main: `9d40eadab7b0f3e123b6edfe5eb9f0e48f847cc3` (#200).
- Local Linux/Python 3.14.6 baseline: **1169 passed, 1 skipped, 0 failures,
  0 errors**, 237.092 s, 1170 collected (see baseline.xml). Docker spawner
  test explicitly NOT_RUN because Docker/Podman unavailable. Sandbox-off
  fixture tests do not establish secure deployment isolation.
- Baseline ruff green; mypy green (44 modules). Core dependencies remain empty;
  editable install plus dev dependencies succeeded. This is not a lockfile or
  vulnerability audit of every optional provider.
- Main GitHub checks were NOT 100% green: Windows/Python 3.11 hit the 60s test
  watchdog while its native-dependency fixture waited for pip (installer has
  a 90s budget). CI job 103759725109. No arbitrary timeout increase applied.
- Open issues: #198 runtime inventory/readiness/refusal evidence, #199 artifact
  provenance and stale published-install claims, #73 model evaluation. #200
  already wired BASE runtime pins; do not undo that trust boundary.

## Council premortem

Single-agent analysis using four review lenses, **not independent spawned
agents or parallel model consensus**. Top five risks and architectural response:

| Risk under 100x load | Review lens | First-principles response / evidence |
|---|---|---|
| Repeated canonicalization amplifies CPU/GIL contention | Systems + Research | Compute each digest and dictionary once per compare; preserve exact digest contract. Fixed-seed build/compare export below. |
| Admission and observability queues grow without bound | Systems | Bounded supervisor/server/export queues needed. Probes evaluate cached state with no per-request I/O checks. No claim that SaaS admission is implemented. |
| Stale ready state after kill or out-of-order shutdown updates | Red team | Start not-ready; irreversible locked drain; real process kill/restart and 10,000 shuffled calls tested. |
| Runtime name presence mistaken for version/ABI compatibility | Research + Red team | Keep #198 open; probes explicitly operational, not dependency attestation. Do not disguise resolver gaps with a health endpoint. |
| False production claims or telemetry leaks erode operator trust | Founder + Red team | Bounded telemetry labels, no arbitrary URLs/headers/errors; honest NOT_RUN evidence; defer release until source-to-artifact and isolation gates pass. |

Founder priority: reliable signed decisions and explicit refusals outrank adding
an unbounded service or claiming traction. Adoption/retention and willingness
to pay were not measured; no 100x business-impact claim.

## Changes and verification

- `perf:` integrity comparison reuses two computed digests and two payloads.
- `feat:` opt-in dependency-free WSGI ProbeApp: /healthz, /readyz, HEAD/405/404,
  fail-closed startup, terminal drain, lock-protected state, JSON event logging,
  optional injected OpenTelemetry tracer. No public execution API, no global
  logging changes, no automatic CLI listener. Operator integration required.
- Targeted: **26/26 pass**, zero skips/errors (1.878 s). New 9 tests cover real
  HTTP disconnect/recovery, child kill/restart, shuffled 10,000-call burst,
  repeated-call tracemalloc retention (<128 KiB bound), telemetry exceptions,
  canonical integrity contract. Existing 17 stress/chaos tests use fake engines;
  they are not evidence of real container kill recovery.
- Full post-change test and remote CI outcomes are recorded in the PR follow-up.
- Telemetry covers probes only, not full verify execution. Synchronous supplied
  handlers can block: bounded nonblocking export/log pipelines are host duties.
- Remediation limit: at most 5 per component; no production failures hidden by
  retry, skip conversion or weakened assertions.

## Measured before / after: 10,000 jobs, 32 threads

Single runs on shared Linux host while full tests ran; **not controlled causal
performance proof**. Fixed seed 20260913, input lengths 64/1024/16384 bytes.
P50/P95/P99 are task service duration with tracemalloc, excluding queue wait.
RSS is whole-process peak, not an isolated allocation or a leak measurement.

| Metric | Before | After | Delta |
|---|---:|---:|---:|
| p50_ms | 0.754 | 0.432 | -42.8% |
| p95_ms | 121.280 | 86.235 | -28.9% |
| p99_ms | 173.554 | 125.900 | -27.5% |
| throughput_jobs_s | 1129.930 | 1682.527 | +48.9% |
| tracemalloc_peak_bytes | 19302245.000 | 19308161.000 | +0.0% |
| rss_max_kib_linux | 113788.000 | 116104.000 | +2.0% |

100-job/one-thread and 10,000-job/32-thread raw results are exported in
baseline-bench.json and post-bench.json, with source hashes and environment.
Ordered result SHA-256 is identical pre/post for both workloads. The 10,000-job
hash is `ed2515dd50bfc03c15d874baf78c82a5e4964bb6f573521889604e72f691d210`.
The harness retains inputs/results; its RAM increase at larger job counts is
not attributed to a daemon. No speedup threshold is enforced from one run.

## Release blockers / acceptance still outstanding

1. Real Docker/Podman sandbox kill, I/O-loss and reconciliation E2E proof.
2. #198 PEP 508/ABI/extras resolution and trusted target inventory, refusal
   phase-history and rerun semantics acceptance.
3. #199 released artifact/source mapping and exact-wheel installation proof.
4. Full supported Python 3.11–3.13 × OS CI green; local runtime is 3.14.
5. Bounded SaaS admission, tenant isolation, SLOs, end-to-end traces and realistic
   sustained load/RSS profiling. No multi-tenant production service exists here.

No tags, package publication, or existing issue closures are part of this PR.
Merge of this limited increment is not an assertion that these gates are met.


## Concurrent branch reconciliation

A concurrent writer pushed four commits and opened #201 while this audit ran.
The initial push correctly refused a non-fast-forward; no force push was used.
Their package and this WSGI adapter were reconciled by moving ProbeApp to
`prod/wsgi.py` and exporting it from the package. Reviewed issues repaired:

- 44 new lint violations; Windows import failure from unconditional resource;
  macOS RSS byte-to-KiB normalization, unavailable Windows metric explicitly -1.
- Tracer used one shared parent across threads and an unbounded finished list;
  now ContextVar parent tokens and bounded deque (default newest 1024 spans).
- Tracer retrieved OTel but never used it; now enters actual API spans, with
  in-memory SDK exporter test when the optional SDK is installed.
- HTTP diagnostic logger leaked arbitrary paths/query values; bounded routes
  only. Nested JSON secret-key redaction and serialized writes added.

The other writer's standalone `serve()` is development-only: unbounded server
threads and arbitrary synchronous readiness callbacks are not production-safe.
Use the documented cached WSGI adapter behind bounded production serving.
Historical 2,000-span/zero-RSS-growth prose is NOT a leak proof. New bounded
history deliberately retains only the newest spans; exporter is authoritative.
The concurrently authored premortem is historical evidence, not an independent
review performed by this agent. This report's limitations supersede its GA tone.


### Verification follow-up

Combined targeted suite: **50 passed, zero skipped/failures/errors**, including
real optional OpenTelemetry SDK export and a regression proving completed-span
counts differ from retained-history length. Dependency-free production unit
lane: 31 passed / 1 optional-SDK skip (32 tests, before accounting test added).
Combined ruff and mypy are green (50 source modules). Local wheel built and
installed to an isolated target; readiness smoke passed. `wheel-smoke.json`
records its SHA-256 and source; this is not the published PyPI artifact.

GitGuardian incident **37238730** flags a synthetic URL string in a redaction
test from commit f464c5a. It is not a real credential. An explanation requesting
authorized false-positive review was posted; the check is NOT bypassed, history
was NOT rewritten, and no all-green/merge-readiness claim is made while it fails.
The actual supplied token was never written to repo files; rotate it after work
because it was exposed in the task conversation.


### Final local full-suite result

Fresh combined collection at source 49bc16f: **1201 passed, 1 skipped,
0 failures, 0 errors / 1202 collected**, 247.082 seconds; `final.xml`.
The skip is the real Docker child-spawner test, NOT a pass. The subsequent
benchmark-accounting test and concurrent synthetic-fixture string adjustment
were verified by a fresh **50/50** targeted suite (`final-targeted.xml`); no
production source changed after the full run began. All shipped-source lint
checks remain green. A second concurrent commit adjusted how the synthetic
query fixture is constructed; it was merged without discarding work. The
historical scanner finding still needs authorized resolution if it persists.

Thus executed local tests are green, but this is NOT 100% executed E2E and NOT
a GA release. Remote CI must independently pass at the final head. No merge
will be forced while required checks fail or are pending.


A concurrent writer later rewrote the shared branch to cb4514c (removing the
historical synthetic-fixture occurrence). I did not perform that force push.
Its tree matched the previously verified production source exactly; the six
remaining evidence/accounting-file changes were reapplied on top as a normal
fast-forward commit, avoiding reintroducing the rewritten history.
