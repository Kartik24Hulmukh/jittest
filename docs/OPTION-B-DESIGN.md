# JitTest Option B Design: Two-Phase In-Container Provisioning

## 1. Problem Statement & Threat Model

In modern Python repositories (e.g., Flask, Django, requests, FastAPI), test suites depend on external packages declared in `pyproject.toml`, `requirements.txt`, or lockfiles.

### The Threat
Host-based provisioning (`pip install -r requirements.txt` or `pip install -e .` on the CI runner) is a critical vulnerability when evaluating untrusted pull requests:
- Candidate PRs can introduce malicious code in `setup.py`, custom PEP 517 build backends (`[build-system.build-backend]`), `sitecustomize.py`, or `.pth` files.
- If these hooks execute with runner network access and unscrubbed host environment, they can exfiltrate CI secrets (e.g., `GITHUB_TOKEN`, deployment keys) or compromise the runner host.

Option D addressed this by refusing execution on dependency-bearing repositories. Option C addressed this by requiring maintainers to pin pre-built container images. Option B provides the dynamic alternative: provisioning dependencies on-demand per PR without ever executing untrusted code with network access.

---

## 2. Core Architecture: The Two-Phase Pipeline

Option B decomposes candidate evaluation into two strictly separated execution phases:

```
[Host Runner (Trusted)]
   │
   ├─ 1. Static Discovery (src/jittest/discovery.py)
   │     └─ Non-executing AST/text parsing of manifests -> Declared dependencies
   │
   ├─ 2. Phase 1: Networked Fetch Container
   │     ├─ Input: Allowlisted package specifications from Discovery
   │     ├─ Network: ENABLED (allowlisted index only)
   │     ├─ Execution: ZERO candidate code executed
   │     ├─ Action: pip download --only-binary :all: --dest /wheelhouse
   │     └─ Output: Ephemeral Wheelhouse Volume
   │
   ├─ 3. Phase 2: Isolated Test Container
   │     ├─ Network: SEVERED (--network none)
   │     ├─ Mounts: Wheelhouse (ro), Candidate Worktree (ro)
   │     ├─ Action: pip install --no-index --find-links=/wheelhouse
   │     ├─ Action: Preflight + Differential Test Execution (pytest)
   │     └─ Output: Structured Test Outcomes (JUnit XML, stdout tail)
   │
   └─ 4. Host Receipt Signing (src/jittest/receipt.py)
         └─ Signs evidence payload with Ed25519 private key held on host
```

---

## 3. Phase 1: Networked Fetch Phase (Wheelhouse Creation)

### Boundary Rules
- **Container Sandbox**: Runs inside a disposable Docker/Podman container.
- **No Candidate Mount**: The candidate repository worktree is **NOT** mounted into the Phase 1 container.
- **Allowlisted Inputs**: Only the package requirement specifications extracted by `discovery.py` are passed in.
- **Index Allowlisting**: Downloads occur strictly from PyPI (`https://pypi.org/simple`) or a configured enterprise mirror via `--index-url`.

### Command Invocation
```bash
docker run --rm \
  -v jt-wheelhouse-<uuid>:/wheelhouse \
  --cap-drop ALL \
  --user 65534:65534 \
  --memory 2g \
  --cpus 2 \
  python:3.12-slim \
  python3 -m pip download \
    --only-binary :all: \
    --dest /wheelhouse \
    --require-hashes \
    -r /tmp/sanitized-requirements.txt
```

### Critical Invariant: Binary Wheels Only (`--only-binary :all:`)
In Option B Version 1, JitTest strictly requires pre-compiled binary wheels (`.whl`).
- Source distributions (`.tar.gz`, `.zip`) require running `setup.py bdist_wheel` or build backend hooks to compile.
- Running compiler build hooks in Phase 1 would execute candidate code while network access is active, violating the trust model.
- If a dependency lacks a pre-built wheel, JitTest refuses execution with:
  ```text
  refusal.code: unsupported_packaging
  refusal.details: dependency requires sdist compilation; only binary wheels allowed in Phase 1
  ```

---

## 4. Phase 2: Network-less Build & Test Phase

Once all binary wheels are downloaded into the isolated volume `jt-wheelhouse-<uuid>`, Phase 2 executes in an entirely network-severed container.

### Boundary Rules
- **Network Disabled**: `--network none` flag is mandatory.
- **Wheelhouse Mounted Read-Only**: `-v jt-wheelhouse-<uuid>:/wheelhouse:ro`.
- **Candidate Mounted Read-Only**: `-v /path/to/worktree:/workspace:ro`.
- **System Root Read-Only**: `--read-only` root filesystem.
- **Zero Host Secrets**: Secrets stripped from environment; allowlisted runtime variables only.

### In-Container Installation
Inside the network-less container, a clean virtual environment installs packages strictly from the local wheelhouse:
```bash
python3 -m venv /tmp/venv
/tmp/venv/bin/pip install \
  --no-index \
  --find-links=/wheelhouse \
  /workspace
```
Even if candidate build hooks execute during `pip install /workspace`, they have:
1. Zero network connectivity (`--network none`) - cannot exfiltrate data or download secondary payloads.
2. Zero access to runner secrets - cannot read environment tokens.
3. Zero write access to host filesystem - cannot persist or tamper with the runner.

### Test Execution
Following installation, JitTest runs the differential test evaluation:
```bash
/tmp/venv/bin/pytest -q --override-ini="addopts=" /workspace/<test_file>
```

---

## 5. Teardown & Process Hygiene

Upon completion of Phase 2 (or on timeout):
1. Test outcomes and stdout tails are extracted from the container.
2. The Phase 2 container is terminated and forcefully removed:
   ```bash
   docker kill jittest-<uuid>
   docker rm -f jittest-<uuid>
   ```
3. The ephemeral wheelhouse volume is deleted:
   ```bash
   docker volume rm jt-wheelhouse-<uuid>
   ```
4. Verification confirms no orphaned containers or volumes remain.

---

## 6. Host Signing Separation

The Ed25519 signing key (`~/.jittest/verify_ed25519.pem`) is never exposed to Phase 1, Phase 2, or any container volume.

Signing occurs exclusively on the host runner OS after all containers and volumes have been destroyed:
- Evidence is collected into the structured dictionary.
- `sign_evidence(evidence, key_path)` calculates the SHA-512 digest and applies the private key.
- The signed receipt is saved to the requested output path.

---

## 7. Refusal Reason Taxonomy for Option B

| Refusal Code | Phase | Cause |
|---|---|---|
| `fetch_network_error` | Phase 1 | Upstream package index unreachable or timeout. |
| `fetch_hash_mismatch` | Phase 1 | Downloaded wheel hash does not match lockfile SHA256. |
| `unsupported_packaging` | Phase 1 | Dependency only available as sdist; building requires network-disabled environment. |
| `offline_install_failed` | Phase 2 | Missing transitive dependency in wheelhouse during offline install. |
| `resource_limit` | Phase 1/2 | Wheelhouse exceeded volume quota (default 1 GB) or OOM killed. |
| `timeout` | Phase 1/2 | Fetch phase exceeded 180s or test phase exceeded 300s. |

---

## 8. Comparison: Option B vs Option C

| Feature | Option C (Trusted Pinned Image) | Option B (Two-Phase In-Container) |
|---|---|---|
| **Maintainer Setup** | Requires maintainer to build, push, and digest-pin a container image. | Zero maintainer setup; auto-provisions from `pyproject.toml` / lockfile. |
| **Execution Latency** | Instant test start (~2-5 seconds). | Slower: Phase 1 download (~15-45 seconds) + Phase 2 install. |
| **Dependency Changes in PR** | Refuses execution if PR adds new dependencies not in image. | Automatically downloads new dependencies declared in PR. |
| **Network at Test Time** | Never (0 network calls). | Phase 1 uses network for fetch; Phase 2 is 0 network calls. |
| **C/Rust Extensions** | Supported (pre-compiled in image). | Only pre-built binary wheels supported; no compilation from sdist. |
| **Maturity** | Specification ready; primary target for Wave 4. | Architectural design document; targeted for Wave 5. |
