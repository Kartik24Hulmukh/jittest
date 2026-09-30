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

This describes the **unpublished candidate**, not PyPI `0.4.1` (see `RELEASE-ARTIFACTS.md`). Maintainers configure runtime images through the trusted BASE repository configuration or an explicit operator environment override. The Action has **no `runtime-image` input**. Install/evaluate candidate source only by exact reviewed commit SHA.

### Option A: BASE `pyproject.toml` (Recommended)

**Not a runnable pin:** the following digest is a placeholder. Replace it with an image you built and validated through a trusted maintainer process. A HEAD-only pin is not authoritative.

```toml
[tool.jittest.runtime]
image = "ghcr.io/pallets/flask-test-runtime@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

### Option B: Operator Environment Variable

This is a trusted operator override, not a candidate-controlled setting. The digest below is also a placeholder.

```bash
export JITTEST_RUNTIME_IMAGE="ghcr.io/pallets/flask-test-runtime@sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

---

## 3a. Implementation status

**Unreleased public-path hardening:** `verify` now passes the resolved BASE
runtime pin to sandbox planning. The Action availability precheck uses the same
BASE policy, and each test is independently validated by `verify`. Invalid pins
refuse verification before provisioning (`image_digest_required`); advisory
Action policy may still return success while reporting the refusal. If BASE has
no pyproject file (or cannot be read), HEAD is **not** a trusted fallback. Only
an explicitly supplied operator environment value can fill that gap. With no
BASE revision at all, the standalone loader retains checkout configuration.

The digest in the examples above is a placeholder, not a published runnable
image. Use an image you built and validated, pinned to its actual registry digest.

**Image-bound inventory:** before readiness, Option C now runs an offline,
read-only, capability-free probe in the digest-pinned image and records exact
`name==version` package pins from `importlib.metadata`. Engine failures, malformed
JSON, and empty inventories fail closed as typed provision-phase refusals
(`image_inventory_failed`, `image_inventory_malformed`, or
`image_inventory_empty`). The probe never mounts the candidate or enables the
network, and engine stderr is not copied into receipts. Required readiness then
checks declared dependencies against this verified inventory.

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

Candidate execution occurs inside an ephemeral container configured with defense-in-depth confinement. This is illustrative, not a copy-paste command: `HOST_UID:HOST_GID` represents the nonroot host identity; a root host uses `65534:65534`. The disposable worktree is writable, while the package mount and container root are read-only:

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
  --user HOST_UID:HOST_GID \
  -v /path/to/worktree:/workspace:rw \
  -v /opt/jittest:/opt/jittest:ro \
  --tmpfs /tmp:rw,exec,nosuid,size=512m \
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
- **Least Privilege**: `--cap-drop ALL` strips all Linux capabilities; execution uses a nonroot host UID/GID (or `65534:65534` when the host is root).
- **Resource Hardening**: Process tree is bounded to 256 PIDs, 2 GB RAM, and 2 CPU cores.
- **Signing Authority Isolation**: The Ed25519 signing private key resides strictly on the host runner (`~/.jittest/verify_ed25519.pem`) and is never mounted into the container.

---

## 6. Dependency Readiness Scope

The candidate enumerates installed distribution names/versions in the approved image with `importlib.metadata` before readiness; this inventory probe does not mount or import the candidate. With required readiness (`JITTEST_READINESS=required`), the supported requirements syntax is checked against that inventory. Missing, failed, malformed or empty inventory produces a typed refusal, never automatic compatibility.

This is not a complete packaging/ABI resolver or a guarantee that a project imports successfully. Unsupported packaging shapes can refuse; ordinary import/collection failures still appear in execution results. No promise is made for arbitrary lockfile formats, native extensions, DB/network fixtures or every dependency-bearing repository. See the actual receipt's refusal code and phase rather than assuming all failures are `image_missing_dependencies`.

## 7. How to Build and Publish a Runtime Image

Maintainers can build and publish runtime images using a separately approved trusted build process. **Never build an untrusted PR Dockerfile or install its requirements on the host to make verification work.** The following is a maintainer-controlled example, not an image built or published by this review:

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
`jittest verify-receipt --require-confined` enforces the signed confinement classification. It does not inspect the runtime daemon, re-execute tests, or independently prove that a producer really used this boundary. Trust the signer and verify externally supplied provenance. Containers share the host kernel; use disposable least-privilege CI runners and maintain the engine/kernel.
