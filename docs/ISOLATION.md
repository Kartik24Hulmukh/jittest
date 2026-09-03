# JitTest Isolation Contract

## 1. Overview & Selected Contract: Option D (D1 — Waived)

- **Defect D1 Status**: **WAIVED via Option D** (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests).
- **Scope**:
  - **Stdlib-only execution in containers**: Candidate tests that require only standard library modules execute inside container isolation (`docker` or `podman`) with `--network none`, unprivileged user, and read-only worktree mounts.
  - **Explicit refusal on dependency-bearing repositories**: Any candidate test targeting a repository that declares external dependencies (e.g. `requirements.txt`, `pyproject.toml`, lockfiles) refuses execution with:
    ```text
    jittest verify: refused - isolation contract cannot import project dependencies in container mode
    ```
- **Brutal Truth**: Option D is an honest refusal, not a general fix. Docker/Podman container mode cannot execute tests for repos with dependencies like Flask, Django, or requests because the host virtual environment is not bind-mounted into the container (which would violate glibc/wheel ABI compatibility). JitTest refuses cleanly instead of falsely claiming isolated execution. This makes it a safer alpha verifier, but not yet an end-to-end product for dependency-bearing pytest repos.

## 2. Provisioning Boundary & Threat Model (D2 — Mitigated, Not Closed)

- **Defect D2 Status**: **MITIGATED** (secrets scrubbed via `_scrubbed_installer_env`, but host `pip` still runs unconfined PR files before sandbox; not claimed fork-safe).
- **Environment Sanitization**: When running package installers (`pip`, `uv`), `jittest` scrubs the runner's environment via `_scrubbed_installer_env()`. All sensitive environment keys matching `TOKEN`, `SECRET`, `KEY`, `PASS`, `AUTH`, `CRED`, or `BEARER` (specifically including `GITHUB_TOKEN` and CI runner secrets) are stripped before executing setup or installer hooks.
- **Host Execution Disclosure**: Dependency installation commands (`pip install -r ...`, `pip install -e ...`) run directly on the host runner prior to container wrapping. While malicious code in a candidate PR's `setup.py` or PEP 517 build backend cannot harvest runner secrets, it still executes unconfined on the host runner OS.
- **Untrusted Forks**: Scrubbing secrets does not equal sandboxing. Do **not** claim that untrusted forks are fully safe from malicious build-time execution until Option B (in-container provisioning) is implemented.

## 3. Container Daemon Status (D9 — Open)

- **Defect D9 Status**: **OPEN** (no real-daemon dependency-bearing isolation proof).
- **Current Verification**: Documenting Option D in documentation does not close an operational gate. CI validates stdlib-only container execution and honest refusal of dependency-bearing repositories.
- **Open Operational Gate**: There is no proof of real container daemon isolation executing a dependency-bearing candidate suite end-to-end. Container-native provisioning (installing dependencies inside the container before running with `--network none`, i.e. Option B/C) remains an open work item.

## 4. GitHub Action Sandbox Resolution & Operational Boundaries (D8)

- **Action Default**: The `action.yml` default for `sandbox-mode` is `required`.
- **Fork Safety**: `action.py` ensures that pull requests from forks or unknown contexts always resolve to `sandbox-mode: required` (even if `sandbox-mode: auto` is supplied), preventing unconfined downgrades on untrusted PRs.
- **Internal PR Resolution under 'auto'**: For trusted internal PRs where capability degradation is acceptable, specifying `sandbox-mode: auto` resolves according to runner capability (container if available, unconfined if absent).
- **Advisory Verifier**: JitTest Mode A is an advisory verifier for pull requests adding or modifying tests, not a blocking production merge gate.
- **Release Pin**: The published package on PyPI is `v0.3.4`. Source code on `main` is an unpublished release candidate and must be referenced strictly by exact commit SHA.
