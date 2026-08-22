# Security Advisory Draft (GHSA): Silent HMAC-SHA256 Fallback in Receipt Signing

**Title**: Unintended Silent Fallback to HMAC-SHA256 When Ed25519 Signing Fails or Is Unconfigured
**Status**: Draft / Disclosed in v0.3.4
**CVE / GHSA ID**: Pending (GHSA-xxxx-xxxx-xxxx)

---

## Summary

In `jittest` versions prior to **0.3.4** (versions `<= 0.3.3`), when an Ed25519 private signing key was not provided or could not be loaded, `sign_evidence` silently degraded to signing evidence artifacts with HMAC-SHA256 rather than raising `SigningKeyError` and failing closed. 

This silent degradation allowed receipts to be generated and signed with symmetric keys without explicit opt-in, leading to ambiguous verification outcomes where consumers expected asymmetric Ed25519 public key attestations.

---

## Severity & CVSS Metrics

- **Severity**: Medium
- **CVSS v3.1 Vector**: `CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N`
- **CVSS Base Score**: **5.3** (Medium)

---

## Affected Versions

- `jittest < 0.3.4` (all versions from 0.1.0 up to 0.3.3).

## Fixed Version

- `jittest >= 0.3.4`

---

## Technical Details & Root Cause

In `src/jittest/receipt.py` (prior to commit fixing Defect R1 in v0.3.4), the receipt signing function caught exceptions during asymmetric key resolution and fell back to generating a local symmetric HMAC-SHA256 signature.

Because downstream verification consumers often run in CI environments to enforce cryptographic proof of differential test execution, receipts signed via HMAC could not be verified by external verifiers using the official Ed25519 public key published in `docs/KEYS.md`.

In version 0.3.4, the silent fallback was removed. If an Ed25519 signing key is missing or invalid, `jittest verify` immediately raises `SigningKeyError`, emits a clean one-line refusal to `sys.stderr`, and exits with return code `2` (fail closed).

---

## Workaround & Mitigation

Users unable to immediately upgrade to `>= 0.3.4` must explicitly provide an Ed25519 signing key via `--signing-key` and verify receipts using:
```bash
jittest verify-receipt <artifact.json> --expected-signer <pubkey_or_fingerprint>
```
Receipts that specify `"algorithm": "HMAC-SHA256"` without prior agreement should be rejected as unverified.

---

## Credits

Discovered and remediated during the internal jittest security and verification audit (Work Order WO-19).
