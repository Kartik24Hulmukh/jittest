# Public Cryptographic Keys & Offline Receipt Verification

`jittest` signs all evidence artifacts (`evidence.json`) using **Ed25519** public-key signatures. Any third party can verify the authenticity and integrity of a `jittest` evidence receipt offline without needing access to private infrastructure.

---

## Official Project Public Key

| Key Property | Value |
| :--- | :--- |
| **Algorithm** | `Ed25519` |
| **Public Key (Hex)** | `74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130` |
| **Key ID / Fingerprint** | `SHA256:74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130` |
| **Status** | Active (`v0.2.0`+) |

---

## Verifying Evidence Receipts Offline

### Using the `jittest` CLI

If you have `jittest` installed (`pip install jittest` with `cryptography`), you can verify any evidence JSON artifact with a single command:

```bash
jittest verify-receipt path/to/evidence.json
```

**Expected Output (Valid Receipt)**:
```text
jittest verify-receipt: [VALID] signature_valid
```

**JSON Output**:
```bash
jittest verify-receipt path/to/evidence.json --json
```
```json
{
  "valid": true,
  "reason": "signature_valid",
  "artifact": "/path/to/evidence.json"
}
```

---

## Manual Offline Verification (Python / `cryptography`)

If you want to verify a receipt independently using standard Python tools:

```python
import json
import base64
from cryptography.hazmat.primitives.asymmetric import ed25519

# 1. Load evidence artifact
with open("docs/evidence/v0.2/flask_01_evidence.json", "r", encoding="utf-8") as f:
    artifact = json.load(f)

# 2. Extract signature block
sig_block = artifact["signature"]
pub_hex = sig_block["public_key"]  # "74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130"
sig_b64 = sig_block["value"]

# 3. Canonicalize artifact payload (strip "signature" key, sort keys, compact JSON)
payload_dict = {k: v for k, v in artifact.items() if k != "signature"}
canonical_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))
canonical_bytes = canonical_json.encode("utf-8")

# 4. Verify Ed25519 signature
pub_bytes = bytes.fromhex(pub_hex)
sig_bytes = base64.b64decode(sig_b64)

public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
try:
    public_key.verify(sig_bytes, canonical_bytes)
    print("SUCCESS: Receipt is authentic and signed by official Ed25519 key.")
except Exception as e:
    print(f"FAILED: Receipt verification error: {e}")
```

---

## Key Rotation Policy

1. **Active Key**: `74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130`
2. **Key Rotation Procedures**:
   - If key compromise is suspected, a new keypair will be published in `docs/KEYS.md` under an updated version tag (`v0.X.Y`).
   - Prior receipts signed with retired keys will remain cryptographically valid against the historic public key stored in `docs/KEYS.md`.
