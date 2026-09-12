# jittest Execution Backlog & Architectural Gap Spec

This document audits the current state of **jittest** (as of v0.3.5, commit `36a60764658ba10509cbb2eb61909036cbd9e275`), identifies all remaining architectural gaps, edge cases, and incomplete tasks, and details their implementation specs.

---

## 1. Audit & Core Assessment

As of commit `36a60764658ba10509cbb2eb61909036cbd9e275`, the repository has passed rigorous hardening. Specifically:
- **D3 (Path containment)**, **D4 (Signer prefix floor)**, **D5 (Receipt verification semantics)**, **D6 (Artifact collision)**, **D7 (Schema/source verdict agreement)**, and **D8 (Action defaults)** are **FULLY CLOSED & MERGED**.
- **D1 (Docker venv discard)** is waived under **Option D** (stdlib-only container mode with strict `VerifyRefusalError` for external dependencies).
- **D2 (Host provisioning)** is mitigated via environment scrubbing, though host `pip` still runs unconfined PR files.
- The unit and integration test suite comprises **884 tests**, which pass cleanly locally under Python 3.14.
- Static quality gates (**Ruff**, **Mypy**) are completely clean across all source files, scripts, and evaluation modules.

However, several architectural features, production pipelines, and security controls remain unmerged or blocked externally. These are compiled into the backlog below.

---

## 2. The Execution Backlog

### Task 1: Option B - Two-Phase In-Container Provisioning
* **Status**: DESIGNED (`docs/OPTION-B-DESIGN.md`), but unimplemented.
* **Gap**: Currently, Option D refuses to run dependency-bearing repositories in container mode, and Option C requires pre-built images. No on-demand containerized provisioning exists.
* **Security Threat**: Evaluated candidate PRs can run malicious Python code during dependencies installation (`setup.py` / PEP 517 build hooks) with active network access and host credentials exposure.
* **Technical Spec**:
  1. **Phase 1 (Fetch Phase)**: Run a networked but candidate-excluded container. Input is package specifications from non-executing AST/text parsing (`discovery.py`). Run `pip download --only-binary :all: --dest /wheelhouse` against PyPI strictly. Refuse SDIST compilation if wheel is unavailable with `unsupported_packaging` refusal code.
  2. **Phase 2 (Execution Phase)**: Spin up an entirely offline container (`--network none`) mounting the Wheelhouse volume (read-only) and the candidate workspace (read-only). Run `pip install --no-index --find-links=/wheelhouse /workspace` and then run pytest.
  3. **Teardown**: Force-remove the execution containers and the ephemeral wheelhouse volumes.
* **Priority**: P0 (Major feature required for full on-demand safety).

### Task 2: Option C - Registry-Published Digest Verification
* **Status**: PLUMBED, but full verification is open.
* **Gap**: The selection layer (`sandbox.py`) supports preflight image mapping, but an end-to-end `jittest verify` of a third-party repository against a registry-published digest is not fully demonstrated/hardened.
* **Technical Spec**:
  1. Enforce strict cryptographic digest pins (e.g., `[tool.jittest.runtime] image = "ubuntu@sha256:..."`) rather than tag names.
  2. Implement local digest-verification preflight before invoking Docker/Podman to ensure the downloaded image's SHA matches the pinned digest exactly.
* **Priority**: P1 (Production container validation safety).

### Task 3: SLSA & Trusted Publishing Integration (Task 25)
* **Status**: OPEN, pending release pipeline modernization.
* **Gap**: `release.yml` uses older, less secure direct credential configurations instead of SLSA or Trusted Publishing (OIDC-based).
* **Technical Spec**:
  1. Migrate `.github/workflows/release.yml` to PyPI Trusted Publishing via OIDC (`permissions: id-token: write`).
  2. Add SLSA generation workflows to publish verifiable build provenance attestation alongside PyPI/GitHub releases.
* **Priority**: P2 (Supply-chain security best practices).

### Task 4: Host Provisioning Sanitization (D2) Fork-Safety
* **Status**: MITIGATED, but not claimed fork-safe.
* **Gap**: While environment variables are scrubbed, untrusted PR files (such as `setup.py` or malicious fixtures) still run unconfined on the host before sandbox boundaries are established.
* **Technical Spec**:
  1. Prevent executing any PR-modified python setup/build hooks on the host.
  2. Outsource dependency discovery completely to static parsing (`discovery.py`) or move setup/build entirely into a transient container.
* **Priority**: P1 (Host execution containment).

---

## 3. Road to Launch: Release Promotion (v0.3.5)

To transition from the current alpha state to an official, stable release:
1. Promote the validated, complete code on `main` (`36a60764658ba10509cbb2eb61909036cbd9e275`) to release candidate status.
2. Publish `v0.3.5` to PyPI and GitHub Releases by tagging the stable HEAD and pushing.
3. Align the public PyPI package version (currently 0.3.4) with the latest validated and audited codebase.
