# Hardening Loop Status

- **Current main SHA**: b528185e01c773614905c00f747a11aa9920d250
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
- **Exact failing test or CI job**: None (All 26 GitHub Actions checks passed on PR #171; 784 local tests passing)
- **Next step**: Secure 2 named maintainers for 14-day advisory SHA-pin trial; draft NLnet/Restack grant proposal; spike Option B in-container provisioning.

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
| 32 render_status.py | OPEN | - |

D9 proof status: **RUN** (`docs/evidence/option-c-proof-D9-2026-09-09.json`, produced by the `option-c-proof` workflow on a real docker daemon). What that record proves: a dependency-bearing candidate ran inside the pinned pilot image, unprivileged, network denied, and passed. What it does not yet prove: a full `jittest verify` of a third-party dependency-bearing repository through the Option C selection layer against a registry-published digest. Nothing in this section claims more than the record says.
