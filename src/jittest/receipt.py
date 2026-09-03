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
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from . import _ed25519

logger = logging.getLogger("jittest.receipt")

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


def _is_hex(s: str) -> bool:
    return bool(s) and all(c in "0123456789abcdef" for c in s)


def _match_single_entry(entry: str, k_hex: str, f_hex: str) -> bool:
    clean = entry.strip().lower()
    if not clean or not _is_hex(clean):
        return False
    # Signer floor: prefix must be at least 16 hex chars (fingerprint length)
    if len(clean) < 16:
        return False
    if len(clean) == 64:
        if k_hex == clean:
            logger.info("Matched full verifying key %s (len=64)", clean)
            return True
        return False
    if len(clean) == 16:
        if f_hex == clean:
            logger.info("Matched fingerprint %s (len=16)", clean)
            return True
        return False
    if 16 < len(clean) < 64:
        if k_hex.startswith(clean):
            logger.info("Matched verifying key prefix %s (len=%d)", clean, len(clean))
            return True
        return False
    return False


def _matches_signer(expected: str, key_hex: str, fingerprint: str) -> bool:
    target = expected.strip().lower()
    k_hex = key_hex.lower()
    f_hex = fingerprint.lower()
    if not target:
        return False
    target_path = Path(expected)
    if target_path.is_file():
        try:
            content = target_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                entry = line.split("#")[0].strip().lower()
                if _match_single_entry(entry, k_hex, f_hex):
                    return True
            return False
        except OSError:
            pass

    return _match_single_entry(target, k_hex, f_hex)


VALID_VERDICTS = {
    "proven_catch",
    "reproduction_catch",
    "collection_catch",
    "refuted",
    "non_discriminating",
    "inconclusive",
}


class ReceiptVerificationResult(tuple):
    """Result of verify_receipt, unpacking as (valid: bool, reason: str)."""

    signature_valid: bool
    signer_status: str
    schema_valid: bool
    provenance_matched: bool | None
    reason: str
    details: dict[str, Any]

    def __new__(
        cls,
        valid: bool,
        reason: str,
        signature_valid: bool = False,
        signer_status: str = "UNVERIFIED",
        schema_valid: bool = False,
        provenance_matched: bool | None = None,
        details: dict[str, Any] | None = None,
    ):
        instance = super().__new__(cls, (valid, reason))
        instance.signature_valid = signature_valid
        instance.signer_status = signer_status
        instance.schema_valid = schema_valid
        instance.provenance_matched = provenance_matched
        instance.reason = reason
        instance.details = details or {}
        return instance


def verify_receipt(
    evidence_input: Path | str | dict[str, Any],
    key_path: Path | str | None = None,
    backend: str | None = None,
    expected_signer: str | Path | None = None,
    expected_base: str | None = None,
    expected_head: str | None = None,
    expected_test_sha256: str | None = None,
    expected_repo: str | None = None,
    check_schema: bool = True,
) -> ReceiptVerificationResult:
    """Verify a receipt using the public key carried inside it, with semantic and provenance checks.

    Args:
        evidence_input: Path to receipt JSON or parsed evidence dictionary.
        key_path: Accepted for backward compatibility.
        backend: Optional backend selection ('vendored' or 'cryptography').
        expected_signer: Verifying key hex, fingerprint prefix, or path to allowlist file.
        expected_base: Optional expected PR base commit SHA.
        expected_head: Optional expected PR head commit SHA.
        expected_test_sha256: Optional expected SHA-256 digest of verified test file source.
        expected_repo: Optional expected repository path or substring.
        check_schema: Whether to validate verdict enums and proven_catch boolean invariants.

    Returns:
        ``ReceiptVerificationResult``, unpacking as ``(valid, reason)``. Never raises
        on malformed or unrecognised input; an unverifiable receipt is a result, not a crash.
    """
    if isinstance(evidence_input, (str, Path)):
        p = Path(evidence_input)
        if not p.exists():
            return ReceiptVerificationResult(False, f"file_not_found: {p}")
        try:
            evidence_dict = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return ReceiptVerificationResult(False, f"invalid_json: {exc}")
    else:
        evidence_dict = dict(evidence_input)

    sig_block = evidence_dict.get("signature")
    if not isinstance(sig_block, dict):
        return ReceiptVerificationResult(False, "missing_signature_block")

    alg = sig_block.get("algorithm", "Ed25519")
    sig_b64 = sig_block.get("value")
    # `public_key` is the pre-0.4 spelling and is still honoured.
    key_hex = sig_block.get("verifying_key") or sig_block.get("public_key")

    if alg in ("HMAC-SHA256", "HMAC"):
        return ReceiptVerificationResult(
            False,
            "legacy_hmac_receipt_not_independently_verifiable: produced by jittest "
            "<= 0.3.2 without cryptography installed. Its key is derivable from "
            "published source, so this artifact cannot establish authorship. Re-run "
            "`jittest verify` to obtain an Ed25519 receipt.",
        )

    if alg != "Ed25519":
        return ReceiptVerificationResult(False, f"unsupported_algorithm: {alg}")

    if not key_hex or not sig_b64:
        return ReceiptVerificationResult(False, "incomplete_signature_block")

    try:
        pub_bytes = bytes.fromhex(key_hex)
        sig_bytes = base64.b64decode(sig_b64)
    except Exception as exc:
        return ReceiptVerificationResult(False, f"malformed_signature_block: {exc}")

    data = _canonical_bytes(evidence_dict)

    try:
        chosen = _select_backend(backend)
    except SigningKeyError as exc:
        return ReceiptVerificationResult(False, f"backend_unavailable: {exc}")

    valid_sig = False
    if chosen == CRYPTOGRAPHY:
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig_bytes, data)
            valid_sig = True
        except Exception as exc:
            return ReceiptVerificationResult(False, f"signature_verification_failed: {exc}", signature_valid=False)
    else:
        if _ed25519.verify(pub_bytes, data, sig_bytes):
            valid_sig = True
        else:
            return ReceiptVerificationResult(
                False, "signature_verification_failed: Ed25519 signature does not match payload", signature_valid=False
            )

    if not valid_sig:
        return ReceiptVerificationResult(
            False, "signature_verification_failed: Ed25519 signature does not match payload", signature_valid=False
        )

    fingerprint = hashlib.sha256(pub_bytes).hexdigest()[:16]

    # Signer Authenticity check
    if not expected_signer:
        signer_status = "UNVERIFIED"
        signer_msg = "SIGNER_UNVERIFIED — integrity only, not authenticity"
    elif _matches_signer(str(expected_signer), key_hex, fingerprint):
        signer_status = "TRUSTED"
        signer_msg = f"SIGNER_TRUSTED (fingerprint: {fingerprint})"
    else:
        signer_status = "UNTRUSTED"
        signer_msg = f"SIGNER_UNTRUSTED: signer fingerprint {fingerprint} does not match expected {expected_signer}"

    # Semantic & Schema validation
    schema_valid = True
    schema_msg = "SCHEMA_VALID"
    if check_schema:
        verdict = evidence_dict.get("verdict")
        if verdict not in VALID_VERDICTS:
            schema_valid = False
            schema_msg = f"SCHEMA_INVALID: unknown_verdict '{verdict}'"
        elif "proven_catch" in evidence_dict:
            pc = evidence_dict.get("proven_catch")
            expected_pc = verdict in ("proven_catch", "reproduction_catch")
            if pc is not expected_pc:
                schema_valid = False
                schema_msg = (
                    f"SCHEMA_INVALID: proven_catch_invariant_violation: "
                    f"verdict '{verdict}' expects proven_catch={expected_pc}, got {pc}"
                )

    # Provenance consistency validation
    provenance_matched: bool | None = None
    prov_msg = ""
    if any(x is not None for x in (expected_base, expected_head, expected_test_sha256, expected_repo)):
        prov = evidence_dict.get("provenance", {})
        mismatches: list[str] = []
        if expected_base is not None:
            actual_b = str(prov.get("base_sha", "")).lower()
            exp_b = str(expected_base).lower()
            if not (actual_b.startswith(exp_b) or exp_b.startswith(actual_b)):
                mismatches.append(f"base_sha mismatch: expected {expected_base}, got {prov.get('base_sha')}")
        if expected_head is not None:
            actual_h = str(prov.get("head_sha", "")).lower()
            exp_h = str(expected_head).lower()
            if not (actual_h.startswith(exp_h) or exp_h.startswith(actual_h)):
                mismatches.append(f"head_sha mismatch: expected {expected_head}, got {prov.get('head_sha')}")
        if expected_test_sha256 is not None:
            actual_s = str(prov.get("test_file_sha256", "")).lower()
            exp_s = str(expected_test_sha256).lower()
            if actual_s != exp_s:
                mismatches.append(
                    f"test_file_sha256 mismatch: expected {expected_test_sha256}, got {prov.get('test_file_sha256')}"
                )
        if expected_repo is not None:
            actual_r = str(prov.get("repo_path", "")).lower()
            exp_r = str(expected_repo).lower()
            if exp_r not in actual_r:
                mismatches.append(f"repo_path mismatch: expected {expected_repo}, got {prov.get('repo_path')}")

        if mismatches:
            provenance_matched = False
            prov_msg = f"PROVENANCE_MISMATCH: {'; '.join(mismatches)}"
        else:
            provenance_matched = True
            prov_msg = "PROVENANCE_MATCHED"

    parts = ["SIGNATURE_VALID", signer_msg, schema_msg]
    if prov_msg:
        parts.append(prov_msg)
    final_reason = " · ".join(parts)

    overall_valid = (
        valid_sig
        and schema_valid
        and (provenance_matched is not False)
    )

    return ReceiptVerificationResult(
        overall_valid,
        final_reason,
        signature_valid=valid_sig,
        signer_status=signer_status,
        schema_valid=schema_valid,
        provenance_matched=provenance_matched,
        details={
            "fingerprint": fingerprint,
            "verifying_key": key_hex,
            "verdict": evidence_dict.get("verdict"),
            "proven_catch": evidence_dict.get("proven_catch"),
        },
    )

