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
import re
import stat
import subprocess
from dataclasses import dataclass
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
    "validate_schema",
    "validate_semantics",
    "normalize_repo_canonical",
    "get_repo_canonical",
    "ReceiptVerificationResult",
    "SchemaResult",
    "SemanticResult",
    "HAS_CRYPTOGRAPHY",
    "SUPPORTED_SCHEMA_VERSIONS",
    "REQUIRED_TOP_LEVEL",
    "REQUIRED_PROVENANCE",
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


def _is_posix() -> bool:
    return os.name == "posix"


def get_or_create_signing_key(key_path: Path | str | None = None) -> bytes:
    """Return the 32-byte Ed25519 seed at ``key_path``, creating it when absent.

    Raises:
        SigningKeyError: the file exists but is not a usable Ed25519 key. The caller
            asked for a specific key; falling back to a different one would silently
            change who signed the receipt.
    """
    if key_path is None:
        env_key = os.getenv("JITTEST_SIGNING_KEY_PATH")
        key_path = Path(env_key) if env_key else _DEFAULT_KEY_PATH
    else:
        key_path = Path(key_path)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    if key_path.exists():
        if _is_posix():
            try:
                mode = key_path.stat().st_mode
                if mode & 0o077:
                    raise SigningKeyError(
                        f"signing key {key_path} is group/world readable (mode: {oct(stat.S_IMODE(mode))}); "
                        "refusing to sign with insecure key permissions"
                    )
            except OSError as exc:
                if isinstance(exc, SigningKeyError):
                    raise
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


SUPPORTED_SCHEMA_VERSIONS = frozenset({"2.0", "2.1"})

REQUIRED_TOP_LEVEL: dict[str, Any] = {
    "schema_version": str,
    "tool": str,
    "verdict": str,
    "proven_catch": bool,
    "disposition": str,
    "provenance": dict,
    "sandbox": dict,
    "base_execution": dict,
    "head_execution": dict,
    "rerun_agreement": bool,
    "wall_clock_s": (int, float),
    "signature": dict,
}

REQUIRED_PROVENANCE: dict[str, Any] = {
    "repo_path": str,
    "base_sha": str,
    "head_sha": str,
    "test_file_name": str,
    "test_file_sha256": str,
    "tool_commit_sha": str,
    "rel_path": str,
}


def _check_type(val: Any, exp: Any) -> bool:
    exp_tuple = exp if isinstance(exp, tuple) else (exp,)
    if not isinstance(val, exp_tuple):
        return False
    return not (isinstance(val, bool) and bool not in exp_tuple)


HEX_40_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HEX_64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

VALID_VERDICTS = {
    "proven_catch",
    "reproduction_catch",
    "collection_catch",
    "refuted",
    "non_discriminating",
    "inconclusive",
}


@dataclass
class SchemaResult:
    valid: bool
    errors: list[str]
    schema_version: str
    status: str = "VALID"  # VALID, INVALID, UNSUPPORTED, VALID_LEGACY


@dataclass
class SemanticResult:
    valid: bool
    errors: list[str]


def normalize_repo_canonical(url: str) -> str:
    url = url.strip()
    if not url:
        return ""
    if url.startswith("local:"):
        return url
    if "@" in url and "://" in url:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            rest = rest.split("@", 1)[1]
        url = f"{scheme}://{rest}"
    elif "@" in url and ":" in url and "://" not in url:
        url = url.split("@", 1)[1]
    if "://" in url:
        url = url.split("://", 1)[1]
    if ":" in url and "/" not in url.split(":", 1)[0]:
        host_part, path_part = url.split(":", 1)
        url = f"{host_part}/{path_part}"
    if url.endswith(".git"):
        url = url[:-4]
    url = url.strip("/")
    parts = url.split("/", 1)
    url = f"{parts[0].lower()}/{parts[1]}" if len(parts) == 2 else url.lower()
    return url


def get_repo_canonical(repo_path: Path | str) -> str:
    p = Path(repo_path).resolve()
    try:
        from .diff import git_env

        res = subprocess.run(
            ["git", "-C", str(p), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            errors="replace",
            env=git_env(),
        )
        if res.returncode == 0 and res.stdout.strip():
            return normalize_repo_canonical(res.stdout.strip())
    except Exception:
        pass
    path_str = str(p).replace("\\", "/").lower()
    path_hash = hashlib.sha256(path_str.encode("utf-8")).hexdigest()[:16]
    return f"local:{path_hash}"


def validate_schema(evidence: dict, require_signature: bool = True) -> SchemaResult:
    if not isinstance(evidence, dict):
        return SchemaResult(False, ["evidence must be a dictionary"], "", status="INVALID")

    schema_version = str(evidence.get("schema_version", ""))
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS and schema_version != "1.0":
        return SchemaResult(
            False,
            [
                f"unsupported schema_version '{schema_version}', expected one of {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            ],
            schema_version,
            status="UNSUPPORTED",
        )

    errors: list[str] = []

    if schema_version in ("1.0", "2.0"):
        verdict = evidence.get("verdict")
        if verdict is not None and verdict not in VALID_VERDICTS:
            errors.append(f"unknown verdict '{verdict}', expected one of {sorted(VALID_VERDICTS)}")
        elif "proven_catch" in evidence:
            pc = evidence.get("proven_catch")
            expected_pc = verdict in ("proven_catch", "reproduction_catch")
            if pc is not expected_pc:
                errors.append(
                    f"proven_catch_invariant_violation: verdict '{verdict}' expects proven_catch={expected_pc}, got {pc}"
                )

        prov = evidence.get("provenance")
        if isinstance(prov, dict):
            for sha_field in ("base_sha", "head_sha"):
                if sha_field in prov and prov[sha_field] and not HEX_40_RE.match(prov[sha_field]):
                    errors.append(
                        f"provenance field '{sha_field}' must be 40-character hex SHA, got '{prov[sha_field]}'"
                    )
            if (
                "test_file_sha256" in prov
                and prov["test_file_sha256"]
                and not HEX_64_RE.match(prov["test_file_sha256"])
            ):
                errors.append(
                    f"provenance field 'test_file_sha256' must be 64-character hex SHA, got '{prov['test_file_sha256']}'"
                )

        if errors:
            return SchemaResult(False, errors, schema_version, status="INVALID")
        return SchemaResult(True, [], schema_version, status="VALID_LEGACY")

    # Schema 2.1 validation
    for k, exp_types in REQUIRED_TOP_LEVEL.items():
        if k == "signature" and not require_signature:
            continue
        if k not in evidence:
            errors.append(f"missing required top-level field: '{k}'")
        elif not _check_type(evidence[k], exp_types):
            errors.append(
                f"field '{k}' must be of type {exp_types}, got {type(evidence[k]).__name__}"
            )

    prov = evidence.get("provenance")
    if not isinstance(prov, dict):
        errors.append("missing required provenance block")
    else:
        for k, exp_types in REQUIRED_PROVENANCE.items():
            if k not in prov:
                errors.append(f"missing required provenance field: '{k}'")
            elif not _check_type(prov[k], exp_types):
                errors.append(
                    f"provenance field '{k}' must be of type {exp_types}, got {type(prov[k]).__name__}"
                )

        if "repo_canonical" in prov and not isinstance(prov["repo_canonical"], str):
            errors.append("provenance field 'repo_canonical' must be of type str")

        for sha_field in ("base_sha", "head_sha", "tool_commit_sha"):
            if (
                sha_field in prov
                and isinstance(prov[sha_field], str)
                and not HEX_40_RE.match(prov[sha_field])
            ):
                errors.append(
                    f"provenance field '{sha_field}' must be a 40-character hex SHA, got '{prov[sha_field]}'"
                )
        if (
            "test_file_sha256" in prov
            and isinstance(prov["test_file_sha256"], str)
            and not HEX_64_RE.match(prov["test_file_sha256"])
        ):
            errors.append(
                f"provenance field 'test_file_sha256' must be a 64-character hex SHA-256, got '{prov['test_file_sha256']}'"
            )

    verdict = evidence.get("verdict")
    if verdict not in VALID_VERDICTS:
        errors.append(f"unknown verdict '{verdict}', expected one of {sorted(VALID_VERDICTS)}")
    elif "proven_catch" in evidence:
        pc = evidence.get("proven_catch")
        expected_pc = verdict in ("proven_catch", "reproduction_catch")
        if pc is not expected_pc:
            errors.append(
                f"proven_catch_invariant_violation: verdict '{verdict}' expects proven_catch={expected_pc}, got {pc}"
            )

    if errors:
        return SchemaResult(False, errors, schema_version, status="INVALID")
    return SchemaResult(True, [], schema_version, status="VALID")


def validate_semantics(evidence: dict) -> SemanticResult:
    if not isinstance(evidence, dict):
        return SemanticResult(False, ["evidence must be a dictionary"])

    errors: list[str] = []
    verdict = evidence.get("verdict")
    rerun_agreement = evidence.get("rerun_agreement")

    refusal_obj = evidence.get("refusal")
    disp = str(evidence.get("disposition", ""))
    has_refusal = refusal_obj is not None or disp.startswith("refused_")
    if has_refusal:
        if verdict != "inconclusive":
            errors.append(f"presence of refusal requires verdict 'inconclusive', got '{verdict}'")
        if evidence.get("proven_catch") is not False:
            errors.append("presence of refusal requires proven_catch=False")
        if refusal_obj is not None and not disp.startswith("refused_"):
            errors.append(
                f"presence of refusal requires disposition starting with 'refused_', got '{disp}'"
            )

    if rerun_agreement is False and verdict in (
        "proven_catch",
        "reproduction_catch",
        "collection_catch",
    ):
        errors.append(f"rerun_agreement=False forbids catch verdict '{verdict}'")

    sbx = evidence.get("sandbox")
    if isinstance(sbx, dict) and sbx.get("backend") == "none" and sbx.get("mode") == "required":
        errors.append("sandbox backend 'none' with mode 'required' is invalid")

    base_exec = evidence.get("base_execution")
    head_exec = evidence.get("head_execution")

    if isinstance(base_exec, dict) and isinstance(head_exec, dict):
        base_outcome = str(base_exec.get("outcome", "")).upper()
        head_outcome = str(head_exec.get("outcome", "")).upper()
        base_fk = str(base_exec.get("failure_kind", "")).lower()
        head_fk = str(head_exec.get("failure_kind", "")).lower()
        is_legacy = str(evidence.get("schema_version", "")) in ("1.0", "2.0")

        if verdict == "proven_catch":
            if base_outcome != "PASS":
                errors.append(
                    f"verdict 'proven_catch' requires base outcome PASS, got '{base_outcome}'"
                )
            if head_outcome != "FAIL":
                errors.append(
                    f"verdict 'proven_catch' requires head outcome FAIL, got '{head_outcome}'"
                )
            if is_legacy:
                if head_fk not in ("assertion", ""):
                    errors.append(
                        f"verdict 'proven_catch' requires head failure_kind 'assertion', got '{head_fk}'"
                    )
            else:
                if head_fk != "assertion":
                    errors.append(
                        f"verdict 'proven_catch' requires head failure_kind 'assertion', got '{head_fk}'"
                    )

        elif verdict == "reproduction_catch":
            if base_outcome != "FAIL":
                errors.append(
                    f"verdict 'reproduction_catch' requires base outcome FAIL, got '{base_outcome}'"
                )
            if is_legacy:
                if base_fk not in ("assertion", ""):
                    errors.append(
                        f"verdict 'reproduction_catch' requires base failure_kind 'assertion', got '{base_fk}'"
                    )
            else:
                if base_fk != "assertion":
                    errors.append(
                        f"verdict 'reproduction_catch' requires base failure_kind 'assertion', got '{base_fk}'"
                    )
            if head_outcome != "PASS":
                errors.append(
                    f"verdict 'reproduction_catch' requires head outcome PASS, got '{head_outcome}'"
                )

        elif verdict == "collection_catch":
            if base_outcome != "PASS":
                errors.append(
                    f"verdict 'collection_catch' requires base outcome PASS, got '{base_outcome}'"
                )
            if is_legacy:
                if head_fk not in ("collection", "import", "") and head_outcome not in (
                    "ERROR",
                    "NOTRUN",
                ):
                    errors.append(
                        f"verdict 'collection_catch' requires head failure_kind in {{collection, import}}, got '{head_fk}'"
                    )
            else:
                if head_fk not in ("collection", "import"):
                    errors.append(
                        f"verdict 'collection_catch' requires head failure_kind in {{collection, import}}, got '{head_fk}'"
                    )

        elif verdict == "refuted":
            if base_outcome != "FAIL" or head_outcome != "FAIL":
                errors.append(
                    f"verdict 'refuted' requires base FAIL and head FAIL, got base={base_outcome}, head={head_outcome}"
                )

        elif verdict == "non_discriminating":
            if base_outcome != "PASS" or head_outcome != "PASS":
                errors.append(
                    f"verdict 'non_discriminating' requires base PASS and head PASS, got base={base_outcome}, head={head_outcome}"
                )

        elif verdict == "inconclusive":
            base_problem = base_outcome in ("ERROR", "TIMEOUT", "NOTRUN") or base_fk in (
                "collection",
                "error",
                "timeout",
            )
            head_problem = head_outcome in ("ERROR", "TIMEOUT", "NOTRUN") or head_fk in (
                "error",
                "timeout",
            )
            disp_ok = disp.startswith("refused_") or disp in (
                "env_setup_failed",
                "env_build_timeout",
                "head_flaky",
                "base_reproduction_failed",
                "base_uncollectable",
                "not_run",
                "head_failed_base_failed_latent",
            )
            if not (
                has_refusal or base_problem or head_problem or rerun_agreement is False or disp_ok
            ):
                errors.append(
                    "verdict 'inconclusive' requires a refusal object, execution error/timeout, or flakiness"
                )

    return SemanticResult(valid=len(errors) == 0, errors=errors)


class ReceiptVerificationResult:
    """Result of verify_receipt, exposing five independent fields while preserving tuple unpacking."""

    def __init__(
        self,
        valid: bool,
        reason: str,
        signature_valid: bool = False,
        signer_status: str = "UNVERIFIED",
        schema_status: str = "INVALID",
        provenance_status: str = "NOT_CHECKED",
        execution_trust: str = "UNKNOWN",
        semantic_valid: bool = True,
        schema_valid: bool | None = None,
        provenance_matched: bool | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.valid = valid
        self.reason = reason
        self.signature_valid = signature_valid
        self.signer_status = signer_status
        self.schema_status = schema_status
        self.provenance_status = provenance_status
        self.execution_trust = execution_trust
        self.semantic_valid = semantic_valid
        if schema_valid and schema_status == "INVALID":
            self.schema_status = "VALID"
        if provenance_matched is not None and provenance_status == "NOT_CHECKED":
            if provenance_matched is True:
                self.provenance_status = "MATCHED"
            elif provenance_matched is False:
                self.provenance_status = "MISMATCH"
        self.details = details or {}

    @property
    def schema_valid(self) -> bool:
        return self.schema_status in ("VALID", "VALID_LEGACY") and self.semantic_valid

    @property
    def provenance_matched(self) -> bool | None:
        if self.provenance_status == "NOT_CHECKED":
            return None
        return self.provenance_status == "MATCHED"

    def __iter__(self):
        yield self.valid
        yield self.reason

    def __getitem__(self, index: int):
        if index == 0:
            return self.valid
        elif index == 1:
            return self.reason
        raise IndexError(f"ReceiptVerificationResult index out of range: {index}")

    def __repr__(self) -> str:
        return (
            f"ReceiptVerificationResult(valid={self.valid!r}, reason={self.reason!r}, "
            f"signature_valid={self.signature_valid!r}, signer_status={self.signer_status!r}, "
            f"schema_status={self.schema_status!r}, provenance_status={self.provenance_status!r}, "
            f"execution_trust={self.execution_trust!r})"
        )


def verify_receipt(
    evidence_input: Any,
    key_path: Path | str | None = None,
    backend: str | None = None,
    expected_signer: str | Path | None = None,
    expected_base: str | None = None,
    expected_head: str | None = None,
    expected_test_sha256: str | None = None,
    expected_repo: str | None = None,
    check_schema: bool = True,
    strict_signer: bool = False,
    require_confined: bool = False,
) -> ReceiptVerificationResult:
    """Verify a receipt using the public key carried inside it, with strict semantic and provenance checks.

    Args:
        evidence_input: Path to receipt JSON, JSON string, or parsed evidence dictionary.
        key_path: Accepted for backward compatibility.
        backend: Optional backend selection ('vendored' or 'cryptography').
        expected_signer: Verifying key hex, fingerprint prefix, or path to allowlist file.
        expected_base: Optional expected PR base commit SHA.
        expected_head: Optional expected PR head commit SHA.
        expected_test_sha256: Optional expected SHA-256 digest of verified test file source.
        expected_repo: Optional expected repository path, canonical identity, or URL.
        check_schema: Whether to validate verdict enums, types, and semantics.

    Returns:
        ``ReceiptVerificationResult``, unpacking as ``(valid, reason)``. Never raises
        on malformed or unrecognised input; an unverifiable receipt is a result, not a crash.
    """
    MAX_INPUT_BYTES = 5 * 1024 * 1024
    if evidence_input is None or not isinstance(evidence_input, (dict, str, Path)):
        return ReceiptVerificationResult(
            False,
            f"invalid_input: expected dict, str, or Path, got {type(evidence_input).__name__}",
            signature_valid=False,
            schema_status="INVALID",
        )

    evidence_dict: dict[str, Any]
    if isinstance(evidence_input, (str, Path)):
        p = Path(evidence_input)
        is_file = False
        try:
            is_file = p.is_file()
        except OSError:
            is_file = False

        if is_file:
            try:
                size = p.stat().st_size
                if size > MAX_INPUT_BYTES:
                    return ReceiptVerificationResult(
                        False,
                        f"invalid_input: evidence file exceeds {MAX_INPUT_BYTES} bytes",
                        signature_valid=False,
                        schema_status="INVALID",
                    )
                raw_text = p.read_text(encoding="utf-8")
                loaded = json.loads(raw_text)
                if not isinstance(loaded, dict):
                    return ReceiptVerificationResult(
                        False,
                        f"invalid_input: JSON root must be an object, got {type(loaded).__name__}",
                        signature_valid=False,
                        schema_status="INVALID",
                    )
                evidence_dict = loaded
            except Exception as exc:
                return ReceiptVerificationResult(
                    False, f"invalid_json: {exc}", signature_valid=False, schema_status="INVALID"
                )
        else:
            str_val = str(evidence_input).strip()
            if len(str_val.encode("utf-8")) > MAX_INPUT_BYTES:
                return ReceiptVerificationResult(
                    False,
                    f"invalid_input: evidence string exceeds {MAX_INPUT_BYTES} bytes",
                    signature_valid=False,
                    schema_status="INVALID",
                )
            if str_val.startswith("{") or str_val.startswith("["):
                try:
                    loaded = json.loads(str_val)
                    if not isinstance(loaded, dict):
                        return ReceiptVerificationResult(
                            False,
                            f"invalid_input: JSON root must be an object, got {type(loaded).__name__}",
                            signature_valid=False,
                            schema_status="INVALID",
                        )
                    evidence_dict = loaded
                except Exception as exc:
                    return ReceiptVerificationResult(
                        False,
                        f"invalid_json: {exc}",
                        signature_valid=False,
                        schema_status="INVALID",
                    )
            else:
                return ReceiptVerificationResult(
                    False, f"file_not_found: {p}", signature_valid=False, schema_status="INVALID"
                )
    elif isinstance(evidence_input, dict):
        evidence_dict = dict(evidence_input)
    else:
        return ReceiptVerificationResult(
            False,
            f"invalid_input: expected dict, str, or Path, got {type(evidence_input).__name__}",
            signature_valid=False,
            schema_status="INVALID",
        )

    execution_trust = "UNKNOWN"
    sbx = evidence_dict.get("sandbox")
    refusal = evidence_dict.get("refusal")
    disp = str(evidence_dict.get("disposition", ""))
    schema_ver = str(evidence_dict.get("schema_version", ""))

    if refusal is not None or disp.startswith("refused_"):
        execution_trust = "REFUSED"
    elif isinstance(sbx, dict):
        mode = sbx.get("mode")
        sbx_backend = sbx.get("backend")
        confined = sbx.get("confined")

        if mode == "off" or sbx_backend == "none" or confined is False:
            execution_trust = "UNCONFINED"
        elif confined is True or (
            sbx_backend in ("docker", "podman", "bubblewrap") and mode != "off"
        ):
            execution_trust = "CONFINED"
        else:
            execution_trust = "UNKNOWN"
    elif schema_ver == "2.0":
        execution_trust = "UNKNOWN"

    sig_block = evidence_dict.get("signature")
    if not isinstance(sig_block, dict):
        return ReceiptVerificationResult(
            False,
            "missing_signature_block",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    alg = sig_block.get("algorithm", "Ed25519")
    sig_b64 = sig_block.get("value")
    key_hex = sig_block.get("verifying_key") or sig_block.get("public_key")

    if alg in ("HMAC-SHA256", "HMAC"):
        return ReceiptVerificationResult(
            False,
            "legacy_hmac_receipt_not_independently_verifiable: produced by jittest "
            "<= 0.3.2 without cryptography installed. Its key is derivable from "
            "published source, so this artifact cannot establish authorship. Re-run "
            "`jittest verify` to obtain an Ed25519 receipt.",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    if alg != "Ed25519":
        return ReceiptVerificationResult(
            False,
            f"unsupported_algorithm: {alg}",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    if not key_hex or not sig_b64:
        return ReceiptVerificationResult(
            False,
            "incomplete_signature_block",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    try:
        pub_bytes = bytes.fromhex(key_hex)
        sig_bytes = base64.b64decode(sig_b64)
    except Exception as exc:
        return ReceiptVerificationResult(
            False,
            f"malformed_signature_block: {exc}",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    data = _canonical_bytes(evidence_dict)

    try:
        chosen = _select_backend(backend)
    except SigningKeyError as exc:
        return ReceiptVerificationResult(
            False,
            f"backend_unavailable: {exc}",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    valid_sig = False
    if chosen == CRYPTOGRAPHY:
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes).verify(sig_bytes, data)
            valid_sig = True
        except Exception as exc:
            return ReceiptVerificationResult(
                False,
                f"signature_verification_failed: {exc}",
                signature_valid=False,
                schema_status="INVALID",
                execution_trust=execution_trust,
            )
    else:
        if _ed25519.verify(pub_bytes, data, sig_bytes):
            valid_sig = True
        else:
            return ReceiptVerificationResult(
                False,
                "signature_verification_failed: Ed25519 signature does not match payload",
                signature_valid=False,
                schema_status="INVALID",
                execution_trust=execution_trust,
            )

    if not valid_sig:
        return ReceiptVerificationResult(
            False,
            "signature_verification_failed: Ed25519 signature does not match payload",
            signature_valid=False,
            schema_status="INVALID",
            execution_trust=execution_trust,
        )

    fingerprint = hashlib.sha256(pub_bytes).hexdigest()[:16]

    # Signer Authenticity check
    if not expected_signer:
        signer_status = "UNVERIFIED"
        signer_msg = "SIGNER_UNVERIFIED - integrity only, not authenticity"
    else:
        exp_str = str(expected_signer).strip()
        if not Path(exp_str).is_file() and (len(exp_str) < 16 or not _is_hex(exp_str)):
            signer_status = "INVALID_FORMAT"
            signer_msg = f"SIGNER_UNTRUSTED: SIGNER_INVALID_FORMAT: expected_signer '{exp_str}' must be at least 16 hex characters"
        elif _matches_signer(exp_str, key_hex, fingerprint):
            signer_status = "TRUSTED"
            signer_msg = f"SIGNER_TRUSTED (fingerprint: {fingerprint})"
        else:
            signer_status = "UNTRUSTED"
            signer_msg = f"SIGNER_UNTRUSTED: signer fingerprint {fingerprint} does not match expected {expected_signer}"

    # Semantic & Schema validation
    schema_res = validate_schema(evidence_dict)
    semantic_res = validate_semantics(evidence_dict) if check_schema else SemanticResult(True, [])

    schema_status = schema_res.status
    if schema_status == "VALID_LEGACY":
        schema_msg = "SCHEMA_VALID_LEGACY: legacy schema 2.0 receipt"
    elif schema_status == "UNSUPPORTED":
        schema_msg = f"SCHEMA_UNSUPPORTED: {'; '.join(schema_res.errors)}"
    elif not schema_res.valid:
        schema_msg = f"SCHEMA_INVALID: {'; '.join(schema_res.errors)}"
    elif not semantic_res.valid:
        schema_msg = f"SEMANTIC_INVALID: {'; '.join(semantic_res.errors)}"
    else:
        schema_msg = "SCHEMA_VALID"

    # Provenance consistency validation
    provenance_status = "NOT_CHECKED"
    prov_msg = ""
    prov_mismatches: list[str] = []
    prov_unresolvable = False

    has_prov_expectation = any(
        x is not None for x in (expected_base, expected_head, expected_test_sha256, expected_repo)
    )
    if has_prov_expectation:
        prov = evidence_dict.get("provenance")
        if not isinstance(prov, dict):
            prov_mismatches.append("missing provenance block in evidence")
        else:
            if expected_base is not None:
                exp_b = str(expected_base).strip().lower()
                actual_b = str(prov.get("base_sha", "")).strip().lower()
                if not exp_b:
                    prov_mismatches.append("expected base_sha is empty")
                elif not actual_b:
                    prov_mismatches.append("actual base_sha is empty")
                elif len(exp_b) < 40:
                    resolved_b = ""
                    repo_hint = prov.get("repo_path")
                    if repo_hint and Path(repo_hint).exists():
                        try:
                            from .execute import resolve_revision

                            resolved_b = resolve_revision(repo_hint, exp_b)
                        except Exception:
                            resolved_b = ""
                    if resolved_b:
                        exp_b = resolved_b.lower()
                    else:
                        prov_unresolvable = True
                        prov_mismatches.append(
                            f"base_sha unresolvable: abbreviated ref '{exp_b}' cannot be resolved without repository"
                        )
                if not prov_unresolvable and exp_b and actual_b != exp_b:
                    prov_mismatches.append(f"base_sha mismatch: expected {exp_b}, got {actual_b}")

            if expected_head is not None:
                exp_h = str(expected_head).strip().lower()
                actual_h = str(prov.get("head_sha", "")).strip().lower()
                if not exp_h:
                    prov_mismatches.append("expected head_sha is empty")
                elif not actual_h:
                    prov_mismatches.append("actual head_sha is empty")
                elif len(exp_h) < 40:
                    resolved_h = ""
                    repo_hint = prov.get("repo_path")
                    if repo_hint and Path(repo_hint).exists():
                        try:
                            from .execute import resolve_revision

                            resolved_h = resolve_revision(repo_hint, exp_h)
                        except Exception:
                            resolved_h = ""
                    if resolved_h:
                        exp_h = resolved_h.lower()
                    else:
                        prov_unresolvable = True
                        prov_mismatches.append(
                            f"head_sha unresolvable: abbreviated ref '{exp_h}' cannot be resolved without repository"
                        )
                if not prov_unresolvable and exp_h and actual_h != exp_h:
                    prov_mismatches.append(f"head_sha mismatch: expected {exp_h}, got {actual_h}")

            if expected_test_sha256 is not None:
                exp_s = str(expected_test_sha256).strip().lower()
                actual_s = str(prov.get("test_file_sha256", "")).strip().lower()
                if not exp_s:
                    prov_mismatches.append("expected test_file_sha256 is empty")
                elif not actual_s:
                    prov_mismatches.append("actual test_file_sha256 is empty")
                elif actual_s != exp_s:
                    prov_mismatches.append(
                        f"test_file_sha256 mismatch: expected {exp_s}, got {actual_s}"
                    )

            if expected_repo is not None:
                exp_repo_raw = str(expected_repo).strip()
                if not exp_repo_raw:
                    prov_mismatches.append("expected repository identity is empty")
                else:
                    exp_repo_norm = normalize_repo_canonical(exp_repo_raw)
                    actual_canonical = str(prov.get("repo_canonical", "")).strip()
                    if not actual_canonical:
                        if prov.get("repo_path"):
                            prov_unresolvable = True
                            prov_mismatches.append(
                                "repo_canonical missing in receipt provenance (legacy v2.0)"
                            )
                        else:
                            prov_mismatches.append("actual repository identity missing")
                    elif actual_canonical.startswith("local:") and not exp_repo_norm.startswith(
                        "local:"
                    ):
                        prov_unresolvable = True
                        prov_mismatches.append(
                            f"PROVENANCE_REPO_UNRESOLVABLE: receipt is from a local checkout without remote ({actual_canonical}), cannot match '{expected_repo}'"
                        )
                    elif actual_canonical.lower() != exp_repo_norm.lower():
                        prov_mismatches.append(
                            f"repo_canonical mismatch: expected '{exp_repo_norm}', got '{actual_canonical}'"
                        )

        if prov_unresolvable:
            provenance_status = "UNRESOLVABLE"
            prov_msg = f"PROVENANCE_UNRESOLVABLE: {'; '.join(prov_mismatches)}"
        elif prov_mismatches:
            provenance_status = "MISMATCH"
            prov_msg = f"PROVENANCE_MISMATCH: {'; '.join(prov_mismatches)}"
        else:
            provenance_status = "MATCHED"
            prov_msg = "PROVENANCE_MATCHED"

    parts = ["SIGNATURE_VALID", signer_msg, schema_msg]
    if prov_msg:
        parts.append(prov_msg)
    final_reason = " · ".join(parts)

    overall_valid = (
        valid_sig
        and (schema_status in ("VALID", "VALID_LEGACY"))
        and semantic_res.valid
        and (provenance_status in ("MATCHED", "NOT_CHECKED"))
    )
    if strict_signer:
        overall_valid = overall_valid and (signer_status == "TRUSTED")
    if require_confined:
        overall_valid = overall_valid and (execution_trust == "CONFINED")

    return ReceiptVerificationResult(
        overall_valid,
        final_reason,
        signature_valid=valid_sig,
        signer_status=signer_status,
        schema_status=schema_status,
        provenance_status=provenance_status,
        execution_trust=execution_trust,
        semantic_valid=semantic_res.valid,
        details={
            "fingerprint": fingerprint,
            "verifying_key": key_hex,
            "verdict": evidence_dict.get("verdict"),
            "proven_catch": evidence_dict.get("proven_catch"),
            "schema_version": schema_res.schema_version,
        },
    )
