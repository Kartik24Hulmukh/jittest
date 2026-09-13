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
