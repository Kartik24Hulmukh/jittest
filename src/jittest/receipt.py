"""Cryptographic Ed25519 Signed Receipts & Hash-Chain Ledger Verification.

Signs evidence JSON artifacts with an Ed25519 private key and provides offline
verification of artifact authenticity via `jittest verify-receipt <file>`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

__all__ = ["get_or_create_signing_key", "sign_evidence", "verify_receipt"]


def get_or_create_signing_key(
    key_path: Path | str | None = None,
) -> tuple[ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey]:
    if key_path is None:
        key_path = Path.home() / ".jittest" / "verify_ed25519.pem"
    else:
        key_path = Path(key_path)

    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        try:
            pem_data = key_path.read_bytes()
            priv_key = serialization.load_pem_private_key(pem_data, password=None)
            if isinstance(priv_key, ed25519.Ed25519PrivateKey):
                return priv_key, priv_key.public_key()
        except Exception:
            pass

    # Generate new key pair
    priv_key = ed25519.Ed25519PrivateKey.generate()
    pub_key = priv_key.public_key()

    pem_bytes = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem_bytes)
    return priv_key, pub_key


def _canonical_bytes(evidence_dict: dict[str, Any]) -> bytes:
    # Copy dict and strip signature block
    d = {k: v for k, v in evidence_dict.items() if k != "signature"}
    canonical_json = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return canonical_json.encode("utf-8")


def sign_evidence(
    evidence_dict: dict[str, Any],
    key_path: Path | str | None = None,
) -> dict[str, Any]:
    priv_key, pub_key = get_or_create_signing_key(key_path)
    data = _canonical_bytes(evidence_dict)
    sig_bytes = priv_key.sign(data)

    pub_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    result = dict(evidence_dict)
    result["signature"] = {
        "algorithm": "Ed25519",
        "public_key": pub_bytes.hex(),
        "value": base64.b64encode(sig_bytes).decode("utf-8"),
    }
    return result


def verify_receipt(
    evidence_input: Path | str | dict[str, Any],
) -> tuple[bool, str]:
    if isinstance(evidence_input, (str, Path)):
        p = Path(evidence_input)
        if not p.exists():
            return False, f"file_not_found: {p}"
        try:
            evidence_dict = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"invalid_json: {exc}"
    else:
        evidence_dict = dict(evidence_input)

    sig_block = evidence_dict.get("signature")
    if not isinstance(sig_block, dict):
        return False, "missing_signature_block"

    pub_hex = sig_block.get("public_key")
    sig_b64 = sig_block.get("value")

    if not pub_hex or not sig_b64:
        return False, "incomplete_signature_block"

    try:
        pub_bytes = bytes.fromhex(pub_hex)
        sig_bytes = base64.b64decode(sig_b64)
        pub_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
    except Exception as exc:
        return False, f"invalid_key_or_signature_format: {exc}"

    data = _canonical_bytes(evidence_dict)

    try:
        pub_key.verify(sig_bytes, data)
        return True, "signature_valid"
    except Exception as exc:
        return False, f"signature_verification_failed: {exc}"
