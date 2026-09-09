# JitTest Isolation Contract

## 1. Overview & Selected Contract: Option D (D1 - Waived)

- **Defect D1 Status**: **WAIVED via Option D** (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests).
- **Scope**:
  - **Stdlib-only execution in containers**: Candidate tests that require only standard library modules execute inside container isolation (`docker` or `podman`) or unprivileged Linux namespaces (`bubblewrap`) with `--network none`, unprivileged user, and read-only worktree mounts.
  - **Explicit refusal on dependency-bearing repositories**: Any candidate test targeting a repository that declares external dependencies (e.g. `requirements.txt`, `pyproject.toml`, lockfiles) refuses execution with:
    ```text
    jittest verify: refused - isolation contract cannot import project dependencies in container mode
    ```
- **Brutal Truth**: Option D is an honest refusal, not a general fix. Docker/Podman container mode cannot execute tests for repos with dependencies like Flask, Django, or requests because the host virtual environment is not bind-mounted into the container (which would violate glibc/wheel ABI compatibility). JitTest refuses cleanly instead of falsely claiming isolated execution. This makes it a safer alpha verifier, but not yet an end-to-end product for dependency-bearing pytest repos.

## 2. Provisioning Boundary & Threat Model (D2 - Closed in J1)

- **Defect D2 Status**: **CLOSED in J1** (zero candidate-controlled code executes on host runner; preflight confined behind sandbox boundary; static manifest discovery).
- **Non-Executing Discovery**: `src/jittest/discovery.py` inspects packaging manifests (`pyproject.toml`, `setup.cfg`, `requirements*.txt`, `setup.py`, lockfiles) strictly through static AST or text parsing with a 1 MiB size cap and strict path containment. It never imports candidate modules, executes candidate code, or invokes build backends on the host.
- **Confined Preflight**: `_preflight_environment()` executes interpreter readiness probes and `pytest --version` checks inside `sandbox.wrap()`. Under `sandbox-mode: required` when no isolation backend is available, it refuses immediately with `VerifyRefusalError("refused:pre_isolation_execution")` or `sandbox_unavailable`.
- **Environment Allowlist**: Inside the isolation boundary, processes receive only an allowlisted set of minimal environment variables:
  - `PATH`
  - `HOME=/tmp/jt-home`
  - `LANG`
  - `PYTHONDONTWRITEBYTECODE=1`
  - `PYTHONNOUSERSITE=1`
  - `PYTHONSAFEPATH=1`
  - `PYTHONPATH` (container-relative workspace)
  - `JITTEST_INSIDE_SANDBOX=1`
  All sensitive runner credentials matching `TOKEN`, `SECRET`, `KEY`, `PASS`, `AUTH`, `CRED`, or `BEARER` (including `GITHUB_TOKEN`) are completely excluded.
- **Host Signing Separation**: The Ed25519 signing key is held strictly by the host process. Signing occurs exclusively on the host after the container exits. Key paths (default `~/.jittest/verify_ed25519.pem` or `JITTEST_SIGNING_KEY_PATH`) are never mounted into containers or passed in environment variables, and POSIX key permissions must be 0600 or stricter.
- **Process Hygiene**: Containers are assigned unique identifiers (`jittest-<uuid4>`). On timeout, the container is killed by name (`docker kill <name>`) and verified removed (`docker ps -a --filter name=`).

## 3. Container Daemon Status (D9 - Open)

- **Defect D9 Status**: **OPEN** (no real-daemon dependency-bearing isolation proof).
- **Current Verification**: CI validates stdlib-only container execution and honest refusal of dependency-bearing repositories.
- **Open Operational Gate**: There is no proof of real container daemon isolation executing a dependency-bearing candidate suite end-to-end. Container-native provisioning (trusted image pinning by digest, i.e. Option C) is owned by Track C and remains open until verified against a real daemon.

## 4. GitHub Action Sandbox Resolution & Operational Boundaries (D8)

- **Action Default**: The `action.yml` default for `sandbox-mode` is `required`.
- **Fork Safety**: `action.py` ensures that pull requests from forks or unknown contexts always resolve to `sandbox-mode: required` (even if `sandbox-mode: auto` or an environment variable is supplied), preventing unconfined downgrades on untrusted PRs.
- **Missing Backend in Fork/Unknown Context**: If trust context is `fork` or `unknown` and no isolation backend is available, `jittest action` emits `::error::`, writes a signed refusal receipt (disposition `refused_sandbox_unavailable`), posts a `REFUSED` PR summary table, and under `advisory` policy exits 0 (or exits 1 under `strict` or `block-on-refusal`).
- **Internal PR Resolution under 'auto'**: For trusted internal PRs where capability degradation is acceptable, specifying `sandbox-mode: auto` resolves according to runner capability (container if available, unconfined with warning if absent).
- **Advisory Verifier**: JitTest Mode A is an advisory verifier for pull requests adding or modifying tests, not a blocking production merge gate.
- **Release Pin**: The published package on PyPI is `v0.3.4`. Source code on `main` is an unpublished release candidate and must be referenced strictly by exact commit SHA.
