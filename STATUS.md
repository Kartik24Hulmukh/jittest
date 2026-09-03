# Hardening Loop Status

- **Current main SHA**: e296c71f17f828d7ec683115542eeb7eb055ebab
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
- **Exact failing test or CI job**: None (Local test suite passing 100%)
- **Next step**: Verify PR checks on GitHub Actions after pushing branch.
