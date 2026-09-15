# Jittest launch closeout — post-#212 merge verification (2026-09-15)

**Launch window:** September 16-17, 2026. **Decision: GO_LAUNCH_NOT_GA** (scoped developer preview; NOT GA).

## Verified state after this session

| Item | Verified value |
|---|---|
| PR #212 | **Merged (squash)** at 31/31 checks success, mergeable_state `clean`, exact tested head `de49934c (squash-merged PR #212 head; branch commits not retained on main)` |
| New protected `main` | `ba4cd9bcc62edd3e7c7a7d6befa69b20905de5d9` |
| Merged branch | `fix/public-readiness-version-boundary` deleted |
| Full launch gate on `main` (`PYTHONPATH=src scripts/launch_gate.py --full`) | **All 7 gates pass** (ruff, version_drift, release_mapping, workflow_cli_contract, receipts_recompute, soak_evidence, tests) |
| Gate decision | `GO_LAUNCH_NOT_GA`, `ga_ready: false` |
| Gate digest | `2494f4fb607fad39421fdeb12c5d3b520f835f8b5e0f43915368aa819c20bbc5` (byte-identical to PR-head digest — deterministic) |
| Gate JSON SHA-256 | `7987b3ae6fc07cc885aa5107921e2436e14fb67b1f080e5fe10f912805359121` |
| Post-merge main CI at snapshot | 21 success / 1 skipped / 1 windows job in progress (required contexts green on PR head pre-merge) |
| Open PRs after merge | 0 (before this closeout PR) |

## Shallow-clone trap confirmed (premortem validated)
On a `--depth 1` clone the anti-fabrication provenance test fails (git history absent) and the gate returns `NO_GO` — fail-closed, exactly as the runbook warns. `git fetch --unshallow` restores a full pass. Runbook requirement re-confirmed empirically this session.

## Honestly still open (GA blockers — owner-gated)
- **#73** funded efficacy evaluation: requires enforceable $2.00 provider-side cap before the 3-PR smoke.
- **#198** trusted runtime inventory: image-bound inventory still absent (Option C `resolved_versions=[]`).
- **#206** official showcase receipt: regeneration requires the official Ed25519 private key (absent by design); no receipt fabricated.
- **#199** post-0.4.1 publication semantics: static gate row retained; remove only in a reviewed, artifact-backed release PR.
- **PAT rotation (CRITICAL):** the token used this session was exposed at channel level; revoke and replace with a fine-grained, repo-scoped, expiring token immediately.

## Launch claim (scoped, defensible)
"Jittest is a differential test-execution gate for agent-authored pull requests. It issues signed, recomputable execution receipts and refuses when it cannot safely establish a result." Do not claim GA, universal regression detection, or blocking-gate readiness.
