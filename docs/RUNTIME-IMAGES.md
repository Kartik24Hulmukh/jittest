# JitTest Runtime Images (Option C) - Trusted Container Specification

## 1. Executive Summary

JitTest Option C provides trusted, pre-built, digest-pinned container environments for Python repositories with external dependencies (e.g., Flask, Django, requests, FastAPI, pandas).

Under the Option D research preview, JitTest cleanly refused execution on any repository declaring third-party dependencies because host virtual environments cannot be safely bind-mounted into container boundaries without introducing glibc/ABI incompatibilities or escaping the trust boundary.

Option C solves this by requiring maintainers to pin an immutable, pre-baked container image containing their project's dependencies. JitTest executes tests entirely within this boundary with zero dynamic network access and zero candidate-controlled code running on the host runner.

---

## 2. Core Philosophy: Zero Host Provisioning

1. **No Host Dependency Installation**: When a trusted runtime image is configured, JitTest skips all host virtual environment creation and package installation (`pip`, `uv`).
2. **Deterministic Immutability**: The image is pinned by cryptographic SHA256 digest (`@sha256:<64-hex>`). Mutable tags (`:latest`, `:main`, `:v1`) are strictly forbidden.
3. **Honest Refusal on Dependency Drift**: If a pull request modifies project dependencies that are not present in the pinned image, JitTest refuses execution with structured code `image_missing_dependencies`. It never falls back to host execution.

---

## 3. Configuration Surface

Maintainers configure runtime images through their repository's `pyproject.toml` or the GitHub Action workflow input.

### Option A: `pyproject.toml` (Recommended)

```toml
[tool.jittest.runtime]
image = "ghcr.io/pallets/flask-test-runtime@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

### Option B: GitHub Action Input (`action.yml`)

```yaml
- uses: Kartik24Hulmukh/jittest@v0.3.5
  with:
    runtime-image: "ghcr.io/pallets/flask-test-runtime@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

### Option C: Environment Variable

```bash
export JITTEST_RUNTIME_IMAGE="ghcr.io/pallets/flask-test-runtime@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

---

## 3a. Implementation status

Implemented in `src/jittest/sandbox.py`: `validate_image_ref` (Rule 1), `load_runtime_image` (Rule 2, base-branch precedence via `git show <base>:pyproject.toml`, env fallback), `image_digest` (Rule 4, local inspect, never pulls) and `plan(runtime_image=...)`. `env.provision_environment` skips host provisioning entirely when a digest-pinned image is selected on docker/podman (`provisioning: option_c_trusted_image`). An unpinned reference is emitted as `jittest: image_digest_required: ...`, recorded in `report.errors`, and ignored - the run continues under the stdlib-only Option-D contract. Defect D9 (a dependency-bearing candidate executed on a real daemon) is closed only by the `option-c-proof` workflow artifact reporting `"status": "RUN"`.

## 4. Security Invariants & Validation Rules

To prevent candidate pull requests from hijacking the isolation environment:

### Rule 1: Mandatory Cryptographic Digest Pinning
Any image reference lacking an `@sha256:` digest is rejected immediately during configuration parsing with refusal code `image_digest_required`:
```text
jittest: image_digest_required: runtime image must be pinned with @sha256:<digest>
```

### Rule 2: Base-Branch Precedence (PR Tamper Resistance)
When evaluating pull requests, configuration is resolved exclusively from the base branch commit (`base_sha`) using:
```bash
git show <base_sha>:pyproject.toml
```
If a candidate PR modifies `[tool.jittest.runtime].image` in its head branch, the head's modification is ignored. Untrusted fork PRs cannot redirect test execution to an untrusted image.

### Rule 3: Candidate Entrypoints & Dockerfiles Ignored
JitTest constructs the container invocation command directly. Any `Dockerfile`, `entrypoint.sh`, or container configuration inside the candidate worktree is treated as inert data and never executed.

### Rule 4: Local Digest Verification
Before running tests, JitTest inspects the local or pulled image digest:
```bash
docker image inspect --format '{{index .RepoDigests 0}}' <image>
```
If the resolved digest differs from the pinned SHA256, execution aborts with refusal code `image_digest_mismatch`.

---

## 5. In-Container Execution Boundary

Candidate execution occurs inside an ephemeral container configured with defense-in-depth confinement:

```bash
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 256 \
  --memory 2g \
  --cpus 2 \
  --ulimit nofile=1024:1024 \
  --user 65534:65534 \
  -v /path/to/worktree:/workspace:ro \
  -v /opt/jittest:/opt/jittest:ro \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -e PATH=/opt/venv/bin:/usr/local/bin:/usr/bin:/bin \
  -e HOME=/tmp/jt-home \
  -e LANG=C.UTF-8 \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONNOUSERSITE=1 \
  -e PYTHONSAFEPATH=1 \
  -e PYTHONPATH=/workspace \
  -e JITTEST_INSIDE_SANDBOX=1 \
  <image> \
  python3 -m pytest -q <test_file>
```

### Boundary Constraints
- **Network Severed**: `--network none` ensures zero outbound or inbound network calls.
- **Root Filesystem Immutable**: `--read-only` prevents modification of system binaries or libraries.
- **Least Privilege**: `--cap-drop ALL` strips all Linux capabilities; `--user 65534:65534` forces execution as `nobody:nogroup`.
- **Resource Hardening**: Process tree is bounded to 256 PIDs, 2 GB RAM, and 2 CPU cores.
- **Signing Authority Isolation**: The Ed25519 signing private key resides strictly on the host runner (`~/.jittest/verify_ed25519.pem`) and is never mounted into the container.

---

## 6. Dependency Readiness Probe

Before differential test execution, JitTest executes a readiness probe inside the container:
```bash
python3 -c "import <top_level_module>"
```
If the module fails to import (e.g. missing dependencies), the command exits with non-zero and JitTest produces a refusal receipt:
- **Verdict**: `inconclusive`
- **Disposition**: `refused_image_missing_dependencies`
- **Refusal Object**:
  ```json
  {
    "code": "image_missing_dependencies",
    "phase": "provision",
    "message": "Pinned runtime image is missing required project dependencies",
    "details": "ModuleNotFoundError: No module named 'flask'"
  }
  ```

---

## 7. How to Build and Publish a Runtime Image

Maintainers can build and publish runtime images using GitHub Actions:

```dockerfile
# Dockerfile.jittest
FROM python:3.12-slim-bookworm

# Install build tools if required for wheel compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install project dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pytest

# Set default unprivileged user
USER 65534:65534
WORKDIR /workspace
```

Build, push, and capture the exact digest:
```bash
docker build -t ghcr.io/org/repo-runtime:latest -f Dockerfile.jittest .
docker push ghcr.io/org/repo-runtime:latest
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/org/repo-runtime:latest
```

Paste the output digest into `pyproject.toml`.

---

## 8. Receipt Schema 2.1 Alignment

When Option C is active, the generated Ed25519 receipt records the image provenance:

```json
{
  "schema_version": "2.1",
  "sandbox": {
    "mode": "required",
    "backend": "docker",
    "image": "ghcr.io/pallets/flask-test-runtime@sha256:e3b0c442...",
    "image_digest": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "backend_version": "27.1.1",
    "kernel": "Linux 6.8.0-1014-azure",
    "confined": true,
    "env_allowlist": [
      "PATH",
      "HOME",
      "LANG",
      "PYTHONDONTWRITEBYTECODE",
      "PYTHONNOUSERSITE",
      "PYTHONSAFEPATH",
      "PYTHONPATH",
      "JITTEST_INSIDE_SANDBOX"
    ]
  }
}
```
Receipt verifiers using `jittest verify-receipt --require-confined` will confirm that execution was strictly confined within the trusted runtime image.
