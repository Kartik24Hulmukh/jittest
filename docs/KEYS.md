# Public Cryptographic Keys & Offline Receipt Verification

`jittest` signs evidence artifacts (`evidence.json`) using **Ed25519** signatures.

Receipts carry the verifying key used to sign them. Verification checks integrity and, when supplied with `--expected-signer`, authenticity against a verifying key or allowlist chosen by the verifier.

---

## Official Project Verifying Key

| Key Property | Value |
| :--- | :--- |
| **Algorithm** | `Ed25519` |
| **Verifying Key (Hex)** | `74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130` |
| **Key Fingerprint (SHA-256 prefix)** | `4059d799af91096f` |
| **Status** | Active (`v0.3.4`+) |

---

## Verifying Evidence Receipts Offline

### Using the `jittest` CLI

Every `jittest` installation includes a pure-Python RFC 8032 Ed25519 backend and requires zero third-party packages to verify receipts.

#### 1. Authenticity Verification (Expected Signer)
When verifying a receipt from a known source, pass `--expected-signer` with the raw verifying key hex, the 16-character fingerprint, or a path to an allowlist file:

```bash
jittest verify-receipt path/to/evidence.json --expected-signer 74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130
# or using fingerprint:
jittest verify-receipt path/to/evidence.json --expected-signer 4059d799af91096f
# or using an allowlist file:
jittest verify-receipt path/to/evidence.json --expected-signer path/to/allowlist.txt
```

**Outcomes & Exit Codes**:
- `SIGNATURE_VALID · SIGNER_TRUSTED` → **Exit 0**: The Ed25519 signature is cryptographically valid and matches the expected signer.
- `SIGNATURE_VALID · SIGNER_UNTRUSTED` → **Exit 3**: The signature is valid, but was produced by an untrusted or unexpected key.
- `SIGNATURE_INVALID` → **Exit 2**: The signature does not match payload or the receipt is malformed.

#### 2. Integrity-Only Verification (Unverified Signer)
If `--expected-signer` is omitted:
```bash
jittest verify-receipt path/to/evidence.json
```
Prints:
```text
jittest verify-receipt: SIGNATURE_VALID · SIGNER_UNVERIFIED — integrity only, not authenticity
```
And exits with code **3** (non-zero) to signal that authorship has not been established.

## Allowlist File Format

An allowlist file contains one allowed hex key or fingerprint prefix per line. Lines starting with `#` and empty lines are ignored:

```text
# Official maintainers
74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130
4059d799af91096f
```

---

## Key Storage & Custody

The private signing key for published project receipts is currently held locally on developer hardware, not inside an HSM or automated CI secret store. Evidence receipts produced by repository maintainers are signed using this developer-held key.

