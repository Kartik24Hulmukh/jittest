# Hardening Loop Status

- **Audited main SHA (before PR #184)**: 5ffc54b452fbc9aa4dd08a64571c9476939032b6
- **Defect Status**:
  - D3 (Path containment in verify.py): CLOSED & MERGED in PR #167
  - D4 (Signer prefix floor in receipt.py): CLOSED & MERGED in PR #167
  - D6 (Unique evidence artifact naming): CLOSED & MERGED in PR #167
  - D7 (Schema/source verdict agreement): CLOSED & MERGED in PR #168
  - D5 (Receipt semantics & provenance verification): CLOSED & MERGED in PR #168
  - D1 (Docker venv discard / Option D refusal): WAIVED via Option D (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests)
  - D2 (Host provisioning sanitization / Job F): MITIGATED (secrets scrubbed via `_scrubbed_installer_env`, but host `pip` still runs unconfined PR files before sandbox; not claimed fork-safe)
  - D8 (Action defaults & artifact hygiene): CLOSED (action.yml default restored to required; fork-aware safety preserved in action.py)
  - D9 (Real container isolation status & Option D contract): **RUN** on a real docker daemon (GitHub Actions ubuntu-latest, run 34385649631, PR #179): dependency-bearing candidate (requests + Flask) executed inside the pinned pilot image with network denied, 2 passed - record in `docs/evidence/option-c-proof-D9-2026-09-09.json`. Still open: an end-to-end `jittest verify` on a third-party dependency-bearing repo via `[tool.jittest.runtime]` with a registry-published digest
  - D10 (Test file scope): DOCUMENTED (Mode A verifier evaluates PR-modified Python tests)
- **Validation status**: PR #184 fixes the N13-incompatible flaky fixture using parent-owned temporary scratch storage and full-checkout identity. Local Python 3.13 validation: 880 pytest tests passed (1 skipped, 131 subtests passed), 731 dependency-free unittest tests passed (12 skipped); focused subprocess/fixture/explain coverage passed 50 tests. Full-package mypy and Ruff pass. Cross-platform CI must pass on the updated PR head before merge; older PR results are not evidence for this head.
- **Next step**: Secure 2 named maintainers for 14-day advisory SHA-pin trial; draft NLnet/Restack grant proposal; design and threat-model Option B before implementation.

## Phase 2 progress (2026-09-09)

| Task | State | Evidence |
|---|---|---|
| 24 isolation-canaries CI job | SHIPPED, gated on docker; bubblewrap reported | `.github/workflows/ci.yml`, `scripts/isolation_canaries.py` |
| 28 error contract + `jittest explain` | SHIPPED | `src/jittest/explain.py`, `docs/ERRORS.md`, `tests/test_cli_explain.py` |
| 29 doctor sandbox honesty | SHIPPED | `jittest doctor` prints `sandbox: NONE ... WILL REFUSE` |
| 30 version drift job | SHIPPED; caught `CITATION.cff` 0.1.0 | `scripts/check_version_drift.py` |
| 36 JSON Schema 2.1 | SHIPPED | `schemas/receipt-2.1.schema.json`, `tests/test_receipt_json_schema.py` |
| 27 PRIVACY.md + observability | SHIPPED: `refusal_code`, `sandbox_backend`, `sandbox_image_digest`, `wall_clock_s` per telemetry line; `wall_clock_s` + `phases` per report | `docs/PRIVACY.md`, `src/jittest/results.py`, `tests/test_phase2_observability_runtime.py` |
| 18-23 Option C plumbing | SHIPPED (selection layer): Rule 1 digest validation, Rule 2 base-branch precedence, `plan(runtime_image=)`, Option C provisioning skip; `option-c-proof` workflow runs the proof on a daemon. **D9 RUN record still open** until that artifact says `RUN` | `src/jittest/sandbox.py`, `src/jittest/env.py`, `.github/workflows/option-c-proof.yml` |
| 25 SLSA / Trusted Publishing | OPEN, requires founder approval to touch `release.yml` | - |
| 32 render_status.py | SHIPPED | `scripts/render_status.py`, `tests/test_render_status.py` |

D9 proof status: **RUN** (`docs/evidence/option-c-proof-D9-2026-09-09.json`, produced by the `option-c-proof` workflow on a real docker daemon). What that record proves: a dependency-bearing candidate ran inside the pinned pilot image, unprivileged, network denied, and passed. What it does not yet prove: a full `jittest verify` of a third-party dependency-bearing repository through the Option C selection layer against a registry-published digest. Nothing in this section claims more than the record says.

## Handoff gap closure (2026-09-12, this workspace)

The 2026-09-12 production-readiness handoff listed five P0 release blockers.
Four of them are now implemented in pure-python, fail-closed form and covered
by tests/test_p0_gates.py (24 tests). Executed in this workspace on top of
commit 85a1534: full dependency-free unittest suite 758 tests, 0 failures,
0 errors, 6 skipped (42 s); Ruff clean over src/tests/scripts/eval; mypy
clean on the four new modules.

- P0-1 two-phase provisioning: src/jittest/provision.py (ProvisioningRefusal,
  ArtifactPin, ProvisionManifest, provision_in_sandbox, engine adapter seam,
  phase-1 network=fetch destroyed then phase-2 network=none; no host fallback).
- P0-3 deterministic readiness: src/jittest/readiness.py (missing direct
  dependency, lock/specifier drift, ABI/platform incompatibility, host-only
  packages).
- P0-4 output trust boundary: src/jittest/outputguard.py (symlink/fifo/
  socket/device/hardlink/traversal/unicode-collision/oversized/undeclared
  refusal; protected-tree immutability snapshot).
- P0-5 receipt integrity: src/jittest/integrity.py (canonical schema
  integrity-1.0 with source/image/deps/policy/command/exit/output hashes,
  refusal reason, explicit incomplete/non-reproducible states, compare_runs).
- Stress: 100 concurrent provisioning jobs, unique temp dirs, cleanup
  asserted (tests/test_p0_gates.py::TestStressConcurrency).

Still open (unchanged, still GA blockers): P0-2 real registry E2E on a live
Docker/Podman daemon (no container engine exists in this workspace), P1
macOS/Windows coverage and OIDC publish rehearsal, P2 named maintainers/SLOs.
Do NOT promote to GA on this commit alone; see docs/PREMORTEM-2026-09-12.md.

## 2026-09-12 round 2 (CI-driven fixes + P0-2 close-out)
- Fixed the windows-latest CI failures on head a403261: gate test no longer calls
  os.mkfifo unconditionally; special-node classification pinned portably.
- Added `src/jittest/registry.py` (authoritative RepoDigests verification,
  fail-closed) + 14 tests; wired into provisioning via `EngineAdapter.inspect_repo_digests`.
- Added `registry-live` job to `.github/workflows/option-c-proof.yml` executing P0-2 on a
  real daemon (resolve platform digest from the registry, pull by digest, verify RepoDigests).
- Suite on this head: 775 tests, 0 failures, 0 errors, 6 skipped; ruff clean; mypy clean (43 files).
- GA label unchanged: **hardened release candidate, NOT GA** until the registry-live job carries
  raw green evidence, the cross-platform matrix is green on the new head, and P2 gates land.
