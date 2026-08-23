# PyPI Release Yank Justifications: v0.2.1, v0.2.4, v0.3.0, v0.3.1, v0.3.2

This document records the exact rationale for yanking historical releases
`0.2.1`, `0.2.4`, `0.3.0`, `0.3.1`, and `0.3.2` from the Python Package
Index (PyPI).

PyPI yanked_reason is currently null for all five releases and must be set
by the maintainer through the PyPI web UI. This document does not substitute
for that action.

---

## Summary of Yanked Releases

| Version | Status | Primary Yank Reasons |
| :--- | :--- | :--- |
| **0.2.1** | **Yanked** | Silent HMAC signing fallback; no sandbox enforcement. |
| **0.2.4** | **Yanked** | Silent HMAC signing fallback; no sandbox enforcement. |
| **0.3.0** | **Yanked** | Silent HMAC signing fallback; broken exit code contract on `COLLECTION_CATCH` (exited 0 on unverified collection failures). |
| **0.3.1** | **Yanked** | Silent HMAC signing fallback; broken exit code contract on `COLLECTION_CATCH`; permissive offline fallback in environment provisioning. |
| **0.3.2** | **Yanked** | Silent HMAC signing fallback; permissive offline fallback in environment provisioning bypassing strict failure isolation. |

---

## Detailed Technical Grounds for Yanking

### 1. Cryptographic Insecurity: Silent HMAC Fallback (< 0.3.4)

- **Affected versions**: 0.2.1, 0.2.4, 0.3.0, 0.3.1, 0.3.2 (all released versions < 0.3.4).
- **Fix**: The HMAC fallback was removed in commit `2be22e5` ("fix(receipt): Ed25519 in every install; remove forgeable HMAC fallback", PR #128). The first released version containing this fix is **v0.3.4**. Version 0.3.3 does not appear in PyPI's version history.
- **Impact**: `src/jittest/receipt.py` fell back to signing evidence with HMAC-SHA256 when Ed25519 private keys were unavailable, instead of failing closed with `SigningKeyError`.
- **Consequence**: Receipts produced by unconfigured runs were cryptographically ambiguous and could not be verified against the project's published public keys.

### 2. Exit Code Invariant Violation on Collection Failures (`COLLECTION_CATCH`)

- **Affected versions**: 0.3.0, 0.3.1, 0.3.2.
- **Impact**: `src/jittest/verify.py` returned `exit_code = 0` when encountering collection breakages (`COLLECTION_CATCH`), despite `proven_catch = False` and `catch_direction = "none"`.
- **Consequence**: CI pipelines checking `$? == 0` treated collection errors as successful behavioral test verifications.

### 3. Fail-Open Offline Dependency Provisioning

- **Affected versions**: 0.3.1, 0.3.2.
- **Impact**: Dependency provisioning in `src/jittest/env.py` allowed test execution to proceed in unisolated host environments when offline or package resolution failed.
- **Consequence**: Contaminated test environments produced false non-discriminating or false inconclusive verdicts.

---

## Supported Releases

- **>= 0.3.4**: Enforces fail-closed Ed25519 signing, honest non-zero exit codes for non-proven verdicts, and strict environment provisioning.
