"""Ed25519-signed evidence receipts, verifiable in every install.

Every receipt jittest emits is signed with Ed25519. Verification uses the public key
carried *in the receipt*, so a stranger can check a receipt they did not produce, on a
machine that shares nothing with ours.

Two interchangeable backends produce byte-identical signatures, because Ed25519 is
deterministic:

* ``vendored``      - :mod:`jittest._ed25519`, pure Python, always available.
* ``cryptography``  - used automatically when that package is importable, purely as a
                      speed optimisation. It is never a correctness precondition.

History, recorded so the mistake is not repeated. Through 0.3.2 a zero-dependency
install fell back to HMAC-SHA256 whose key was ``sha256(str(key_path) +
b"jittest_fallback_seed")``. That key is derivable from published source, so any third
party could mint a receipt asserting ``proven_catch``; verification also compared
against the *verifier's* local key rather than the receipt's, so receipts did not
survive crossing a machine boundary. Separately, a zero-dependency install could not
verify Ed25519 at all, which meant it could not check jittest's own published evidence.
Symmetric signing is therefore removed rather than repaired: an evidence tool must not
emit an artifact whose authorship it cannot establish.

Receipts written before this change name the public key ``public_key``; that spelling is
still accepted when verifying. New receipts use ``verifying_key``.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from pathlib import Path
from typing import Any

from . import _ed25519

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

# Retained for backwards compatibility with existing imports.
_HAS_CRYPTOGRAPHY = HAS_CRYPTOGRAPHY

__all__ = [
    "SigningKeyError",
    "get_or_create_signing_key",
    "sign_evidence",
    "verify_receipt",
    "HAS_CRYPTOGRAPHY",
]

VENDORED = "vendored"
CRYPTOGRAPHY = "cryptography"

# DER prefix of a PKCS#8 Ed25519 private key. The remaining 32 bytes are the seed.
_PKCS8_ED25519_PREFIX = bytes.fromhex("302e020100300506032b657004220420")

_DEFAULT_KEY_PATH = Path.home() / ".jittest" / "verify_ed25519.pem"


class SigningKeyError(Exception):
    """Raised when a signing key was requested but cannot be used.

    Never swallowed. A key the user named and we silently ignored is how 0.3.2
    produced receipts that failed their own verifier.
    """


def _seed_to_pem(seed: bytes) -> bytes:
    if len(seed) != _ed25519.SEED_SIZE:
        raise SigningKeyError(f"ed25519 seed must be {_ed25519.SEED_SIZE} bytes")
    der = _PKCS8_ED25519_PREFIX + seed
    body = base64.encodebytes(der).decode("ascii").strip()
    return f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----\n".encode()


def _seed_from_pem(data: bytes) -> bytes:
    """Extract the 32-byte seed from PKCS#8 PEM, PKCS#8 DER, or a raw 32-byte key."""
    if len(data) == _ed25519.SEED_SIZE and b"-----" not in data:
        return data

    text = data.decode("ascii", errors="ignore")
    if "-----BEGIN" in text:
        lines = [
            ln.strip()
            for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith("-----")
        ]
        try:
            der = base64.b64decode("".join(lines))
        except Exception as exc:
            raise SigningKeyError(f"key is not valid base64 PEM: {exc}") from exc
    else:
        der = data

    if der.startswith(_PKCS8_ED25519_PREFIX) and len(der) == len(_PKCS8_ED25519_PREFIX) + 32:
        return der[-32:]
    raise SigningKeyError(
        "key is not a PKCS#8 Ed25519 private key (expected a 48-byte DER structure "
        "or a raw 32-byte seed)"
    )


def get_or_create_signing_key(key_path: Path | str | None = None) -> bytes:
    """Return the 32-byte Ed25519 seed at ``key_path``, creating it when absent.

    Raises:
        SigningKeyError: the file exists but is not a usable Ed25519 key. The caller
            asked for a specific key; falling back to a different one would silently
            change who signed the receipt.
    """
    key_path = Path(key_path) if key_path is not None else _DEFAULT_KEY_PATH
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        try:
            data = key_path.read_bytes()
        except OSError as exc:
            raise SigningKeyError(f"cannot read signing key {key_path}: {exc}") from exc
        return _seed_from_pem(data)

    seed = os.urandom(_ed25519.SEED_SIZE)
    key_path.write_bytes(_seed_to_pem(seed))
    # Windows and some mounted filesystems do not support POSIX modes. The key is
    # still written; permissions simply follow the platform default.
    with contextlib.suppress(OSError):
        key_path.chmod(0o600)
    return seed


def _canonical_bytes(evidence_dict: dict[str, Any]) -> bytes:
    d = {k: v for k, v in evidence_dict.items() if k != "signature"}
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _select_backend(backend: str | None) -> str:
    if backend in (VENDORED, CRYPTOGRAPHY):
        if backend == CRYPTOGRAPHY and not HAS_CRYPTOGRAPHY:
            raise SigningKeyError("cryptography backend requested but not installed")
        return backend
    if backend is not None:
        raise SigningKeyError(f"unknown backend: {backend}")
    return CRYPTOGRAPHY if HAS_CRYPTOGRAPHY else VENDORED


def sign_evidence(
    evidence_dict: dict[str, Any],
    key_path: Path | str | None = None,
    backend: str | None = None,
) -> dict[str, Any]:
    """Return ``evidence_dict`` with an Ed25519 ``signature`` block attached."""
    seed = get_or_create_signing_key(key_path)
    data = _canonical_bytes(evidence_dict)
    chosen = _select_backend(backend)

    if chosen == CRYPTOGRAPHY:
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        sig_bytes = priv.sign(data)
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    else:
        sig_bytes = _ed25519.sign(seed, data)
        pub_bytes = _ed25519.secret_to_public(seed)

    result = dict(evidence_dict)
    result["signature"] = {
        "algorithm": "Ed25519",
        "verifying_key": pub_bytes.hex(),
        "value": base64.b64encode(sig_bytes).decode("utf-8"),
    }
    return result


def verify_receipt(
    evidence_input: Path | str | dict[str, Any],
    key_path: Path | str | None = None,
    backend: str | None = None,
) -> tuple[bool, str]:
    """Verify a receipt using the public key carried inside it.

    ``key_path`` is accepted for call-compatibility and deliberately unused: a receipt
    that can only be checked against the verifier's own key is not evidence.

    Returns:
        ``(valid, reason)``. Never raises on malformed or unrecognised input; an
        unverifiable receipt is a result, not a crash.
    """
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

    alg = sig_block.get("algorithm", "Ed25519")
    sig_b64 = sig_block.get("value")
    # `public_key` is the pre-0.4 spelling and is still honoured.
    key_hex = sig_block.get("verifying_key") or sig_block.get("public_key")

    if alg in ("HMAC-SHA256", "HMAC"):
        return False, (
            "legacy_hmac_receipt_not_independently_verifiable: produced by jittest "
            "<= 0.3.2 without cryptography installed. Its key is derivable from "
            "published source, so this artifact cannot establish authorship. Re-run "
            "`jittest verify` to obtain an Ed25519 receipt."
        )

    if alg != "Ed25519":
        return False, f"unsupported_algorithm: {alg}"

    if not key_hex or not sig_b64:
        return False, "incomplete_signature_block"

    try:
        pub_bytes = bytes.fromhex(key_hex)
        sig_bytes = base64.b64decode(sig_b64)
    except Exception as exc:
        return False, f"malformed_signature_block: {exc}"

    data = _canonical_bytes(evidence_dict)

    try:
        chosen = _select_backend(backend)
    except SigningKeyError as exc:
        return False, f"backend_unavailable: {exc}"

    if chosen == CRYPTOGRAPHY:
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig_bytes, data)
            return True, "signature_valid"
        except Exception as exc:
            return False, f"signature_verification_failed: {exc}"

    if _ed25519.verify(pub_bytes, data, sig_bytes):
        return True, "signature_valid"
    return False, "signature_verification_failed: Ed25519 signature does not match payload"
