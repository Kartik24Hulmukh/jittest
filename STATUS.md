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
  - D9 (Real container isolation status & Option D contract): OPEN (no real-daemon dependency-bearing isolation proof; docs/ISOLATION.md documents Option D contract)
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
| 27 PRIVACY.md | SHIPPED (telemetry field extension still open) | `docs/PRIVACY.md` |
| 18-23 Option C plumbing | PARTIAL: image + proof script; `[tool.jittest.runtime]` selection and D9 RUN record still open | `docker/pilot-requests/`, `scripts/prove_option_c.py` |
| 25 SLSA / Trusted Publishing | OPEN, requires founder approval to touch `release.yml` | - |
| 32 render_status.py | OPEN | - |

D9 remains **NOT_RUN**. Nothing in this section claims a dependency-bearing candidate has executed on a real daemon.
