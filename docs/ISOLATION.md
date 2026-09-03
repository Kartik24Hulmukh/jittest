# JitTest Isolation Contract

## 1. Overview & Selected Contract: Option D

JitTest isolates the execution of candidate tests to protect runner infrastructure and prevent test code from accessing secrets or exfiltrating data.

Per the decision framework in `04-ISOLATION-CONTRACT.md`, JitTest implements **Contract Option D — Restricted Support**:

- **Stdlib-only execution in containers**: Candidate tests that require only standard library modules execute inside container isolation (`docker` or `podman`) with `--network none`, unprivileged user, and read-only worktree mounts.
- **Explicit refusal on dependency-bearing repositories**: Any candidate test targeting a repository that declares dependencies (e.g. `requirements.txt`, `pyproject.toml`, lockfiles) refuses with:
  ```text
  jittest verify: refused - isolation contract cannot import project dependencies in container mode
  ```
- **Rationale**: Container backends run inside immutable slim images (`python:3.13-slim`). Naively bind-mounting the runner's host virtualenv into the container discards glibc/wheel ABI compatibility and creates a false impression of containerized dependency execution. Option D fails closed honestly rather than silently degrading or guessing.

## 2. Provisioning Boundary & Threat Model (D2)

Before candidate tests are executed in the container, `jittest` provisions virtual environments to inspect dependencies:

- **Environment Sanitization**: When running package installers (`pip`, `uv`), `jittest` scrubs the runner's environment via `_scrubbed_installer_env()`. All sensitive environment keys matching `TOKEN`, `SECRET`, `KEY`, `PASS`, `AUTH`, `CRED`, or `BEARER` (specifically including `GITHUB_TOKEN` and runner secrets) are stripped.
- **Host Execution Disclosure**: In the current architecture, dependency installation commands (`pip install -r ...`, `pip install -e ...`) run on the host runner prior to container wrapping. While attacker code inside `setup.py` cannot access runner secrets or tokens, it does execute within the runner OS before the container sandbox starts.
- **Untrusted Forks**: Do not claim that `sandbox-mode: required` provides complete sandbox containment for malicious `setup.py` hooks from untrusted forks until Option B (in-container provisioning) is implemented.

## 3. Container Daemon Status (D9)

- Container isolation is validated for stdlib-only execution and explicit refusal of dependency-bearing tests.
- Full container-native provisioning (building and installing dependencies inside the container before executing with `--network none`) is designated for a future architectural release.
- Real container daemon runs against complex third-party stacks (e.g. Flask, Django) will require Option B/C.

## 4. Operational Boundaries

- **Advisory Verifier**: JitTest is an advisory verifier for pull requests adding or modifying tests. It is not currently a production merge gate.
- **Release Pin**: The published package on PyPI is `v0.3.4`. Source code on `main` is an unpublished release candidate (0.3.5) and must be evaluated strictly by exact commit SHA.
