# September 2026 hardening continuation: evidence inspection

## Decision

**Do not promote main to production-ready.** This is a bounded hardening iteration, not a claim of GA, universal confinement, or 100x traction. No release/tag/publish workflow was triggered. Independent agent tools are unavailable in this environment; parallel test/static-analysis/research processes and security/reliability/product review perspectives were used, not fabricated agent votes.

Audited baseline: `a1c24533fc5e3fe24239f74847064013d100cb76`.
Local environment: Linux, Python 3.14.6. Docker/Podman absent; bubblewrap installed but unusable according to `jittest doctor`. Thus no local confined E2E proof is claimed.

## Newly reproduced and repaired

`src/jittest/outputguard.py` had the following defects:

- Normal nested directories were misclassified as hardlinks (directory link counts are not regular-file hardlink counts).
- Resolving the evidence root erased a root symlink before validation.
- `os.walk` permission errors could produce a clean-looking incomplete scan; a disappearing entry leaked a raw filesystem exception.
- File limits were checked only after traversing the entire tree; directory-only trees had no entry budget. Invalid limits were accepted.
- Protected-tree snapshots followed file symlinks, read whole files into memory, and could block reading special files. Missing roots looked like empty trees.
- Snapshots ignored permission changes and empty-directory additions.

The patch refuses incomplete scans, rejects unsafe roots/nodes, streams regular-file hashing, checks open-file identity before/after hashing, detects mode/directory changes, and stops on file/byte/entry overflow. Added 17 stdlib-unittest regression methods, including 100 independent jobs on 16 threads and FIFO/hardlink refusal.

Initial 13-method regression run against baseline: pytest reported **16 failed, 1 passed** including subtest failures. Two new API expectations (`max_entries`) were absent by design; these are not claimed as independently exploitable vulnerabilities. After implementation and four additional regression methods, focused new + existing P0 tests: **44 passed, 4 subtests passed**.

### Explicit residual limits

These APIs inspect **quiescent trees only**: the runner must terminate candidate descendants, use trusted ancestor directories, and revoke writable access before scanning. Descriptor identity/no-follow checks are defense in depth, not a portable solution to concurrent parent-directory replacement. `os.walk` can allocate one large directory before entry limits take effect. Snapshotting an entire source tree has no global byte/time budget. Enforce filesystem quotas, wall-clock limits and job cancellation outside this helper. No security claim is made for inspection while attacker-controlled writers remain alive.

## Critical integration gap

Source-reference audit found **no production callers outside their own modules** for `provision_in_sandbox`, `evaluate_readiness`, or `scan_output_tree` / `snapshot_tree`. `integrity.py` likewise has no production import discovered in `src`. These P0 modules are useful contract prototypes, not proof that the normal verifier applies them. This patch does not silently wire them into an unreviewed execution path.

Next: design an explicit execution state machine: trusted base policy → confined fetch → frozen manifest → network-off execution → terminate descendants → guarded evidence export → parent-side signed receipt. Every transition must fail closed. Feed CLI and Action through the same implementation; prove rejection via adversarial tests at the **public interface**, not only direct helper calls.

## Existing work and release drift

Open PR [#186](https://github.com/Kartik24Hulmukh/jittest/pull/186) already handles provisioning cleanup, typed refusals, streaming wheel hashing and release/version fixes. Do not duplicate or take credit for it. GitHub check-runs API at its exact head `8722586d6d3924257255e4dde9ec88d613822929` returned 31 completed/success checks, including the nine-platform/Python matrix, `prove`, and `registry-live`. These are evidence about that PR, **not this patch** or current main.

Current main has `pyproject.toml` 0.4.0 but runtime/changelog/citation 0.3.5; `scripts/check_version_drift.py` fails. Main CI [34717178119](https://github.com/Kartik24Hulmukh/jittest/actions/runs/34717178119) failed. Main release tests still contain `|| true`, allowing publication despite failures. PR #186 proposes repairs; merge only after review and retesting its merge candidate.

PyPI JSON API now reports **0.4.0**, uploaded 2026-09-12T20:30:49Z (wheel). README's statement that only 0.3.4 is published is stale. This is distribution metadata, not evidence that the published artifact is safe or identical to the working tree. Audit the published wheel and provenance; do not issue another release as a workaround. The exposed task credential must be revoked/rotated by its owner; it was not stored in repository files or Git remotes.

## Review council: perspectives, not independent agents

| Perspective | Objection | Decision / acceptance evidence |
|---|---|---|
| Security | Scanners can be bypassed by concurrent mutation; helper tests do not prove CLI enforcement | Keep quiescent-tree contract explicit; block GA on public-interface confined attacks |
| Reliability | Cleanup failure or evidence truncation can masquerade as success | Review #186; require typed refusal, unresolved-cleanup reporting, bounded runner and non-skippable real-daemon evidence |
| Product | Another broad generator competes on noisy comments, not trusted decisions | Concentrate on agent-authored Python **bug-fix proof** in advisory mode |
| Measurement | 2 stars / 1 fork and historical cohort execution are not traction or current accuracy | Publish attempted denominator, refusal reasons, cost/latency and maintainer-accepted outcomes |
| Release | Version naming and signed receipts can hide missing runtime guarantees | Require provenance, artifact smoke test, version concordance and exact-merge-head green CI |

## September execution plan and premortem

Dates are proposed from this audit (13 September), not claims that past roadmap deadlines were met. Owners must be assigned by the maintainer.

| Priority / target | Failure premortem | Better solution | Measurable gate |
|---|---|---|---|
| P0 / immediate | Published package passes a bypassed gate | Freeze new releases; review #186; inspect existing 0.4.0 artifact; protected OIDC publishing | Inject a failing test and prove no publish job runs; version check and clean wheel-install smoke pass |
| P0 / Sept 16 | Helper contracts are mistaken for end-to-end enforcement | One parent-owned execution state machine and narrow supported runtime profiles | CLI + Action dependency-bearing fixture passes in pinned network-off image; hostile setup, network, output and descendant canaries refuse |
| P0 / Sept 18 | Receipt signed by an unsafe worker looks authoritative | Parent-only signing, fresh key custody, receipt bound to source/image/dependencies/policy/results | Tamper/replay/substitution tests fail; trusted signer and confinement checks enforced independently |
| P1 / Sept 20 | Environment restoration dominates refusals | Maintainer-approved immutable runtime profiles, cached by dependency hash and platform; no automatic host fallback | Frozen recent-PR cohort with per-reason refusals and cold/warm p50/p95; target >=80% definitive executions in the declared supported slice |
| P1 / Sept 23 | Maintainers turn off a noisy bot | One concise advisory result per PR, explicit inconclusive state and replay command; no speculative comments | Two named consenting maintainers, 14-day SHA-pin trial, instrumented accepted/rejected proof feedback |
| P2 / Sept 30 | Installations do not become retained use | Agent SDK emits a proof request; verifier returns portable evidence; charge hypothesis around saved review time, not tokens | >=2 retained weekly-active repositories, >=20 eligible attempted PRs, at least 3 maintainer-accepted useful proofs; otherwise narrow or stop |
| P2 / before GA | Maintainer absence turns an incident into a supply-chain failure | Two named maintainers, incident lead, rollback and key-revocation rehearsal | Timed rehearsal, documented support window and explicit rollback owner |

Targets above are **proposed**, not achieved. Zero observed false positives in a small sample is not a zero-risk claim. Report uncertainty and intended-change disagreements separately. A 100x business outcome cannot be promised by coding in a session; establish time-saved and retained-use baselines before claiming a multiplier.

## Research basis (accessed 2026-09-13)

- [GitHub secure-use reference](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions): least privilege, rotate exposed credentials, protect workflow trust boundaries. Apply to separate fetch/run/sign/publish privileges.
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/): short-lived OIDC credentials avoid long-lived PyPI publishing secrets; project/publisher configuration still needs verification.
- [PyPI project JSON](https://pypi.org/pypi/jittest/json): live distribution version and upload metadata.
- [Main source](https://github.com/Kartik24Hulmukh/jittest/tree/a1c24533fc5e3fe24239f74847064013d100cb76), [PR #186](https://github.com/Kartik24Hulmukh/jittest/pull/186), and exact-head GitHub check-runs API: state and overlap analysis.
- [Qodo Cover](https://github.com/qodo-ai/qodo-cover): correct live competitor repository (API: 5,644 stars, 557 forks, not archived at audit). Popularity is not revenue or maintenance quality. The stale `qodo-ai/cover-agent` link returned 404; roadmap financial/abandonment assertions were not independently established here and should not drive strategy.

## Recompute

```bash
python -m pip install -e '.[dev]'
python -m pytest tests/test_outputguard_boundaries.py tests/test_p0_gates.py --timeout=30
python -m ruff check src tests scripts eval
python -m mypy src/jittest
python scripts/check_version_drift.py
python -m pytest --timeout=60
```

New tests use stdlib unittest and capability-skip POSIX-only checks; the full OS matrix still must run on the PR head. Repository-configured mypy does not check all untyped function bodies. A failing main baseline must not be hidden by excluding unrelated failures from the final validation record.

## Additional measured evidence

### Published wheel inspection (downloaded, not executed)

PyPI wheel `jittest-0.4.0-py3-none-any.whl`, SHA-256
`19e545368cca8af8c074c36fee4e41da56fc87cf0d776c65ccc70c4703992132`,
matched PyPI's advertised digest. ZIP inspection found metadata version **0.4.0** but runtime `__version__ = "0.3.5"`. Its `outputguard.py` is byte-identical to audited main, so the inspected helper defects are present in that distribution. Digest matching establishes download integrity, not trusted provenance. Raw metadata inspection: `outputguard-wheel-audit.json`.

### Memory experiment

32 snapshot jobs, eight threads, one shared quiescent 8 MiB regular file, three trials per variant. Median peak **Python-traced** allocation: baseline **64.10 MiB**, patched **3.12 MiB** (~20.6x lower). Median wall time: **0.108 s → 0.116 s** (not a speed improvement). All 32 file-content hashes and sizes matched in each trial. This is a warm-cache synthetic allocation benchmark, not RSS, production throughput, or a 100x product result. Additional checks and directory records deliberately change snapshot semantics. Raw first-run results: `outputguard-benchmark.json`; recompute from repository root with `python scripts/bench_outputguard.py` (requires baseline commit in local history).

### Actual CLI probes

A new local toy Git repository with correct addition at base and subtraction at head produced `proven_catch`, PASS → assertion FAIL, rerun agreement true, signed schema 2.1 receipt, in **6.45 s**. This used **explicit `--no-sandbox`** on code authored for this diagnostic only; tool tree was dirty due to test evidence/generated benchmark files. It is not a third-party or confined proof. Receipt verification returned valid signature/schema, signer UNVERIFIED, provenance NOT_CHECKED, execution UNCONFINED. Rechecking with `--require-confined` refused (exit **7**). `--sandbox-mode required` refused before execution because no usable backend exists.

README's official-key receipt example independently verified with signer TRUSTED and legacy schema valid, but execution UNCONFINED and provenance NOT_CHECKED. Signed integrity must not be conflated with confined execution.

### Full-suite provenance

Baseline on main: **922 passed, 2 failed, 1 skipped, 131 subtests passed** in 237.40 s. Both failures are version consistency tests. First candidate full run (13 new regression methods collected before four more methods were added): **935 passed, 2 failed, 1 skipped, 135 subtests passed** in 237.94 s; same two version failures, no other failures. The complete 17-method new test module passed dependency-free under `PYTHONPATH=src python -S -m unittest tests.test_outputguard_boundaries -v` (17 tests, 0.096 s). A fresh full run with all 17 methods and an isolated composition with PR #186 were started separately; report their final results explicitly rather than relabeling the earlier 13-method run.

PR delivery: [#189](https://github.com/Kartik24Hulmukh/jittest/pull/189). Code commit `e7d28f7140af6c74685f17f11ad02d2b84751fbb` (rebased onto `main` after #186 merged as `e3b73972ba61473cdbbe29b4a4a2bb521a9f48a7`; the original pre-rebase code head `a7ce15e` is no longer reachable from any branch, which is why the SHA below is the rebased one). The rebased head runs the full remote matrix in CI before merge.

### Follow-up P0 findings (not repaired in this scoped patch)

`readiness.check_lock_drift("requests>=2.0", "requests==2.32.0")` reports drift even though that pin satisfies the range: it compares strings, not PEP 440 semantics. `check_platform_compat` checks OS/architecture substrings but ignores CPython tags: a cp310/cp310 manylinux x86_64 wheel is accepted on this CPython 3.14 x86_64 host. `parse_requirements("-r other.txt")` produces a fake package named `-r` instead of interpreting or explicitly refusing includes. Before wiring readiness into production, either use a reviewed standards-compliant parser behind an explicit dependency boundary or adopt a narrow canonical manifest and refuse unsupported syntax; do not expand ad-hoc regular expressions and call it resolver parity.

The toy bug-fix probe returned `reproduction_catch` in 13.33 s; the unchanged-base control returned `non_discriminating` in 7.99 s. Both were explicitly unconfined diagnostics, not production proofs. These and the tamper probe complement the initial regression probe. Tampering with receipt text is rejected with invalid signature (exit 2). Remote PR #189 Linux/Python 3.11 raw job log confirms its full suite's only failures were the two existing version tests; that is not a green PR. Other in-progress matrix jobs cannot be treated as passed.

### Composition test completed

An isolated detached worktree at PR #186 head `8722586d6d3924257255e4dde9ec88d613822929` accepted a clean cherry-pick of this patch's pre-rebase code commit (`a7ce15e`, now rebased as `e7d28f7140af6c74685f17f11ad02d2b84751fbb`), producing local composition `853c1f9` (not pushed or merged). Complete pytest: **965 passed, 1 skipped, 143 subtests passed in 244.00 s**. Version drift check passed (0.4.0 in all four checked locations); repository Ruff and configured mypy (43 files) passed. Outputguard source and all 17 regression methods were byte-identical in both worktrees. This establishes local compatibility of the two proposals, not green remote CI or confined E2E for the composition.

Stress repeat: the 100-independent-job / 16-thread scan regression was executed ten additional times, all **1,000/1,000** scan outcomes correct (17.99 s including ten pytest process startups). This is filesystem helper concurrency, not container throughput.

### Final standalone full run

With all 17 new methods collected: **939 passed, 2 failed, 1 skipped, 135 subtests passed in 241.97 s**. Both failures remain the baseline runtime/version-drift tests. No other failures. Raw baseline, initial candidate, final standalone, combined and dependency-free logs are committed under `docs/reports/outputguard-validation/`. No tests were excluded to make the standalone result green.

**Recommended merge sequence:** review/merge #186 first (with current merge-head checks), then update #189 against that main and rerun remote matrix + non-skippable real-daemon proofs. The local combined run is encouraging evidence, not permission to bypass branch protections or declare GA.
