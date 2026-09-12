# Wave-100x Premortem (2026-09-12, round 3)

Failure modes 11-15 discovered by treating the "successful" v0.4.0 release as a
crime scene. Each entry names the executed guard that now blocks it.

## FM-11: Manufactured green release gates
**Failure**: a release workflow exits 0 no matter what the test suite says,
so a broken artifact is published and every dashboard shows green.
**Found by**: v0.4.0 shipped with a failing suite hidden behind `|| true`.
**Guard (executed)**: `|| true` removed from `.github/workflows/release.yml`;
the full pytest suite now runs with no masking; any failure aborts build,
publish and release jobs. Verified by running the honest suite in this
workspace: it found the real 2-failure version-drift block underneath.

## FM-12: Version drift between package metadata and runtime
**Failure**: `pyproject.toml` says X, `__version__` says Y; the published
wheel lies about its own identity and provenance verification rots.
**Found by**: v0.4.0 wheel reports `jittest.__version__ == "0.3.5"`.
**Guard (executed)**: `scripts/check_version_drift.py` + `test_hardening.py`
+ `test_version_drift.py`; all four sources now agree at 0.4.0 in this
branch, and the drift job is fail-closed in CI.

## FM-13: Container leak on mid-pipeline engine failure
**Failure**: engine explodes at phase-2 create; the phase-1 network-enabled
container survives as a quiet egress channel.
**Guard (executed)**: `tests/test_chaos_resilience.py` detonates the engine
at every seam. Healthy cleanup destroys each acquired container; destroy
failure is an unresolved resource requiring reconciliation, not evidence of
zero leaks. See `HARDENING-CONTINUATION.md` for the corrected ownership
contract and paired-failure regressions.

## FM-14: Between-phase digest drift (TOCTOU on the image pin)
**Failure**: the digest verified at phase 1 is not the digest running at
phase 2 - a mirror or local tag was swapped between phases.
**Guard (executed)**: `provision_in_sandbox` re-inspects immediately before
phase-2 create; 50-job drift storm in `tests/test_stress_100x.py` asserts
phase-2 is never created and phase-1 is destroyed.

## FM-15: Silent acceptance of adversarial dependency vectors
**Failure**: `-e git+...`, `file://`, local paths or editable installs slip
past the wheelhouse contract and execute arbitrary code at install time.
**Guard (executed)**: 5-vector parametrized chaos test + 200-job mixed
honest/evil storm assert refusal happens *before any container is created*
with 100% decision accuracy.

## Standing limits (honest, unchanged)
- This workspace has **no Docker/Podman daemon**: P0-2 live-registry E2E and
  the macOS/Windows matrix remain CI-only gates. Nothing here claims that
  evidence.
- The PAT shared in the task prompt is exposed in task history; rotate it.
  Publishing is OIDC-only (`id-token: write`), no token is stored in repo.
