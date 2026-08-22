# PyPI Release Yank Justifications: v0.3.1, v0.3.2, v0.3.3

This document records the exact rationale for yanking historical releases `0.3.1`, `0.3.2`, and `0.3.3` from the Python Package Index (PyPI).

---

## Summary of Yanked Releases

| Version | Status | Primary Yank Reasons |
| :--- | :--- | :--- |
| **0.3.1** | **Yanked** | Silent HMAC signing fallback; Broken exit code contract on `COLLECTION_CATCH` (exited 0 on unverified collection failures). |
| **0.3.2** | **Yanked** | Silent HMAC signing fallback; Permissive offline fallback in environment provisioning bypassing strict failure isolation. |
| **0.3.3** | **Yanked** | Silent HMAC signing fallback (`sign_evidence`); Incorrect baseline resolution in detached worktree containers. |

---

## Detailed Technical Grounds for Yanking

### 1. Cryptographic Insecurity: Silent HMAC Fallback (< 0.3.4)
- **Impact**: In all versions `< 0.3.4`, `src/jittest/receipt.py` fell back to signing evidence with HMAC-SHA256 when Ed25519 private keys were unavailable, instead of failing closed with `SigningKeyError`.
- **Consequence**: Receipts produced by unconfigured runs were cryptographically ambiguous and could not be verified against the project's published public keys.

### 2. Exit Code Invariant Violation on Collection Failures (`COLLECTION_CATCH`)
- **Impact**: `src/jittest/verify.py` returned `exit_code = 0` when encountering collection breakages (`COLLECTION_CATCH`), despite `proven_catch = False` and `catch_direction = "none"`.
- **Consequence**: CI pipelines checking `$? == 0` treated collection errors as successful behavioral test verifications.

### 3. Fail-Open Offline Dependency Provisioning
- **Impact**: Dependency provisioning in `src/jittest/env.py` allowed test execution to proceed in unisolated host environments when offline or package resolution failed.
- **Consequence**: Contaminated test environments produced false non-discriminating or false inconclusive verdicts.

---

## Supported Releases

- **>= 0.3.4**: Enforces fail-closed Ed25519 signing, honest non-zero exit codes for non-proven verdicts, and strict environment provisioning.
