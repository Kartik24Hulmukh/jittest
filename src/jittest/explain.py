"""``jittest explain``: turn a receipt into a sentence a reviewer can act on.

The verifier already exposes five independent facts (signature, signer, schema,
provenance, execution trust). This module renders them, plus the verdict, into a
short human explanation with a *hint* naming the one thing to do next. The
``--json`` form is a stable contract: keys are additive-only within schema 2.x.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .receipt import ReceiptVerificationResult, verify_receipt

__all__ = ["EXIT_CODES", "HINTS", "exit_code_for", "explain_receipt", "render_text"]

# One table for the exit codes, shared with the docs (docs/ERRORS.md).
EXIT_CODES: dict[int, str] = {
    0: "ok: every requested check passed",
    2: "signature_invalid: payload tampered or signature block malformed",
    3: "signer_untrusted: signer not in the allowlist (or unverified under --strict-signer)",
    4: "schema_invalid: receipt schema invalid or unsupported version",
    5: "semantic_invalid: a verdict invariant is violated",
    6: "provenance_mismatch: base/head/test/repo do not match what was expected",
    7: "not_confined: execution was not inside a sandbox boundary",
}

HINTS: dict[int, str] = {
    0: "nothing to do; cite the receipt by its test_file_sha256 and head_sha.",
    2: "fetch the original artifact from the CI run; do not trust a re-serialised copy.",
    3: "pass --expected-signer with the CI signing key fingerprint listed in docs/KEYS.md.",
    4: "regenerate with jittest >= 0.3.5; schema 2.0 receipts prove integrity, not execution trust.",
    5: "the receipt is internally inconsistent; treat the verdict as unproven and rerun jittest verify.",
    6: "compare --expected-base/--expected-head with the PR SHAs; a stale receipt is not evidence.",
    7: "rerun with JITTEST_SANDBOX=required on a runner that has docker, podman or bubblewrap.",
}

VERDICT_TEXT: dict[str, str] = {
    "proven_catch": "the candidate test PASSES on base and FAILS (assertion) on head: it catches the change",
    "reproduction_catch": "the candidate test reproduces a reported failure on head that base does not exhibit",
    "collection_catch": "the candidate test collects on base but head breaks collection or import",
    "refuted": "the candidate test fails on both revisions; the claimed catch is refuted",
    "non_discriminating": "the candidate test passes on both revisions; it proves nothing about the change",
    "inconclusive": "execution was refused, timed out or disagreed across reruns; no claim is made",
}


def exit_code_for(
    res: ReceiptVerificationResult,
    *,
    strict_signer: bool = False,
    expected_signer: str | None = None,
    require_confined: bool = False,
) -> int:
    """Map a verification result onto the documented exit-code table."""
    if not res.signature_valid:
        return 2
    if res.schema_status in ("INVALID", "UNSUPPORTED"):
        return 4
    if not res.semantic_valid:
        return 5
    if res.provenance_status in ("MISMATCH", "UNRESOLVABLE"):
        return 6
    if (
        (strict_signer and res.signer_status != "TRUSTED")
        or (expected_signer is not None and res.signer_status != "TRUSTED")
        or res.signer_status in ("UNTRUSTED", "INVALID_FORMAT")
    ):
        return 3
    if require_confined and res.execution_trust != "CONFINED":
        return 7
    return 0


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def explain_receipt(
    artifact: Path | str,
    *,
    expected_signer: str | None = None,
    strict_signer: bool = False,
    require_confined: bool = False,
) -> dict[str, Any]:
    """Return a JSON-serialisable explanation of ``artifact``. Never raises."""
    path = Path(artifact)
    res = verify_receipt(
        path,
        expected_signer=expected_signer,
        strict_signer=strict_signer,
        require_confined=require_confined,
    )
    code = exit_code_for(
        res,
        strict_signer=strict_signer,
        expected_signer=expected_signer,
        require_confined=require_confined,
    )
    raw = _load(path)
    prov = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
    sbx = raw.get("sandbox") if isinstance(raw.get("sandbox"), dict) else {}
    verdict = raw.get("verdict")
    return {
        "explain_version": 1,
        "artifact": str(path),
        "exit_code": code,
        "code": EXIT_CODES[code].split(":", 1)[0],
        "hint": HINTS[code],
        "verdict": verdict,
        "verdict_text": VERDICT_TEXT.get(str(verdict), "unknown verdict"),
        "schema_version": raw.get("schema_version"),
        "checks": {
            "signature_valid": res.signature_valid,
            "signer_status": res.signer_status,
            "schema_status": res.schema_status,
            "semantic_valid": res.semantic_valid,
            "provenance_status": res.provenance_status,
            "execution_trust": res.execution_trust,
        },
        "provenance": {
            "repo_canonical": prov.get("repo_canonical") or prov.get("repo_path"),
            "base_sha": prov.get("base_sha"),
            "head_sha": prov.get("head_sha"),
            "test_file_name": prov.get("test_file_name"),
            "test_file_sha256": prov.get("test_file_sha256"),
        },
        "sandbox": {
            "backend": sbx.get("backend"),
            "image": sbx.get("image"),
            "network_denied": sbx.get("network_denied"),
        },
        "reason": res.reason,
    }


def render_text(info: dict[str, Any]) -> str:
    c = info["checks"]
    p = info["provenance"]
    s = info["sandbox"]
    ok = info["exit_code"] == 0
    lines = [
        f"jittest explain: {info['artifact']}",
        f"  verdict      : {info['verdict']} ({info['verdict_text']})",
        f"  signature    : {'valid' if c['signature_valid'] else 'INVALID'}; signer {c['signer_status']}",
        f"  schema       : {c['schema_status']} (version {info['schema_version']})",
        f"  semantics    : {'consistent' if c['semantic_valid'] else 'VIOLATED'}",
        f"  provenance   : {c['provenance_status']}; {p['repo_canonical']} {str(p['base_sha'])[:12]}..{str(p['head_sha'])[:12]}",
        f"  execution    : {c['execution_trust']}; sandbox backend {s['backend']}, image {s['image']}, network denied {s['network_denied']}",
        f"  result       : {'OK' if ok else 'REFUSED'} (exit {info['exit_code']}, {info['code']})",
        f"  hint         : {info['hint']}",
    ]
    if not ok:
        lines.append(f"  reason       : {info['reason']}")
    return "\n".join(lines)
