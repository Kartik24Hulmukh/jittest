# JitTest Isolation Contract

## 1. Scope: default Option D and candidate Option C

- **Defect D1 Status**: **WAIVED via Option D** (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests).
- **Scope**:
  - **Stdlib-only execution in containers**: Candidate tests that require only standard library modules execute inside container isolation (`docker` or `podman`) or unprivileged Linux namespaces (`bubblewrap`) with `--network none`, unprivileged user, and writable disposable worktrees (the tool package and container root are read-only).
  - **Default Option D refusal on dependency-bearing repositories without an approved runtime**: Any candidate test targeting a repository that declares external dependencies (e.g. `requirements.txt`, `pyproject.toml`, lockfiles) refuses execution with:
    ```text
    jittest verify: refused - isolation contract cannot import project dependencies in container mode
    ```
- **Brutal Truth**: Option D is an honest refusal, not a general fix. Docker/Podman container mode cannot execute tests for repos with dependencies like Flask, Django, or requests because the host virtual environment is not bind-mounted into the container (which would violate glibc/wheel ABI compatibility). JitTest refuses cleanly instead of falsely claiming isolated execution. The unpublished candidate adds Option C: a trusted digest-pinned BASE runtime plus image-bound inventory. That does not guarantee compatibility with arbitrary packaging, ABI, database or network-dependent tests. See `RUNTIME-IMAGES.md`; only an exact reviewed candidate SHA provides this later behavior.

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

## 3. Container Daemon Status (D9 - Real-Daemon Proof RUN)

- **Defect D9 Status**: **RUN** on a real docker daemon (GitHub Actions `ubuntu-latest`, commit `9537581` in PR #179, Option C pilot image): dependency-bearing candidate (requests + Flask) executed inside the pinned pilot image with `--network none`, 2 passed. Record in `docs/evidence/option-c-proof-D9-2026-09-09.json`.
- **Current Verification**: Validated on real docker daemon; pilot image built and executed with network denied and unprivileged containment.
- **Scope Caveat**: An end-to-end `jittest verify` on a third-party dependency-bearing repository through the `[tool.jittest.runtime]` selection layer with a registry-published digest remains the next hardening milestone.

## 4. GitHub Action Sandbox Resolution & Operational Boundaries (D8)

- **Action Default**: The `action.yml` default for `sandbox-mode` is `required`.
- **Fork Safety**: `action.py` ensures that pull requests from forks or unknown contexts always resolve to `sandbox-mode: required` (even if `sandbox-mode: auto` or an environment variable is supplied), preventing unconfined downgrades on untrusted PRs.
- **Missing Backend in Fork/Unknown Context**: If trust context is `fork` or `unknown` and no isolation backend is available, `jittest action` emits `::error::`, writes a signed refusal receipt (disposition `refused_sandbox_unavailable`), posts a `REFUSED` PR summary table, and under `advisory` policy exits 0 (or exits 1 under `strict` or `block-on-refusal`).
- **Internal PR Resolution under 'auto'**: For trusted internal PRs where capability degradation is acceptable, specifying `sandbox-mode: auto` resolves according to runner capability (container if available, unconfined with warning if absent).
- **Advisory Verifier**: JitTest Mode A is an advisory verifier for pull requests adding or modifying tests, not a blocking production merge gate.
- **Release Pin**: The published package on PyPI is `0.4.1` (`v0.4.1`, source `ef08ddbc`); see `RELEASE-ARTIFACTS.md` for the verified mapping and missing candidate features. Source code on `main` is an unpublished release candidate and must be referenced strictly by exact reviewed commit SHA.

## 5. What confinement does not establish

`verify-receipt --require-confined` validates signed producer metadata, not an independent live-daemon attestation. A signature proves payload integrity and, with a trusted expectation, signer identity; it does not prove test sufficiency or full code correctness. Retained real-daemon evidence is tied to its recorded source/environment and is not a fresh test of every later revision.

Containers share the host kernel; writable worktrees and temporary storage allow candidate file creation. Resource flags limit individual containers, not aggregate runner admission/fairness. Bubblewrap binds essential system paths including `/opt` read-only; read-only access is not confidentiality. Keep secrets out of all mounted directories (including checkout and tool/venv paths), use disposable least-privilege runners, and do not present `auto`/`off` as safe for untrusted code. Environment filtering alone is not a sandbox.
