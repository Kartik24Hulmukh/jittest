"""Security validation arms: forged receipt rejection and sandbox enforcement.

These arms are NOT part of the WO-17 pre-registration.
They probe jittest's security boundaries.

  forged      — Write a forged HMAC receipt and verify it is rejected.
  unsandboxed — Run with sandbox_mode=required when no sandbox is available;
                expect SANDBOX_UNAVAILABLE refusal (verify_test should fail).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from jittest.diff import git_env
from jittest.receipt import verify_receipt


def _parse_fail_to_pass(instance: dict[str, Any]) -> list[str]:
    raw = instance.get("FAIL_TO_PASS", [])
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            return result if isinstance(result, list) else []
        except (ValueError, TypeError):
            return []
    return raw if isinstance(raw, list) else []


def run_security_arm(
    instance: dict[str, Any],
    arm: str,
    output_dir: Path,
) -> dict[str, Any]:
    inst_id = instance["instance_id"]
    base_sha = instance["base_commit"]
    output_dir.mkdir(parents=True, exist_ok=True)
    out_artifact = output_dir / f"{inst_id}_{arm}_evidence.json"

    if arm == "forged":
        forged_data = {
            "schema_version": "0.3.5",
            "tool": "jittest",
            "verdict": "proven_catch",
            "proven_catch": True,
            "disposition": "catching",
            "provenance": {
                "base_sha": base_sha,
                "head_sha": "forged_head_sha",
            },
            "signature": {
                "algorithm": "HMAC-SHA256",
                "verifying_key": "forged_key",
                "value": "forged_signature_value",
            },
        }
        with open(out_artifact, "w", encoding="utf-8") as fh:
            json.dump(forged_data, fh, indent=2)

        is_valid, msg = verify_receipt(out_artifact, expected_signer="official_ed25519_key")
        return {
            "instance_id": inst_id,
            "arm": arm,
            "verdict": "rejection",
            "signature_valid": is_valid,
            "msg": msg,
            "passed_expected_arm_check": not is_valid,
        }

    elif arm == "unsandboxed":
        # This arm tests that verify_test refuses when sandbox_mode=required but no sandbox exists.
        # We don't import verify_test to avoid running arbitrary code — we just document that
        # running with --sandbox-mode required on a host without a container backend should
        # produce a non-zero exit code and a SANDBOX_UNAVAILABLE evidence artifact.
        return {
            "instance_id": inst_id,
            "arm": arm,
            "note": "unsandboxed arm: run verify_test with sandbox_mode=required to confirm refusal",
            "status": "[UNVERIFIED] requires sandbox-capable environment to test properly",
        }

    else:
        raise ValueError(f"Unknown security arm: {arm!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Security validation arms (NOT WO-17)")
    parser.add_argument("--manifest", default="eval/swebench_lite_20.json")
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--arm", choices=["forged", "unsandboxed"], required=True)
    parser.add_argument("--output-dir", default="eval/security_arm_results")
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        instances = json.load(fh)

    match = next((i for i in instances if i["instance_id"] == args.instance_id), None)
    if not match:
        print(f"Instance {args.instance_id} not found in {args.manifest}", file=sys.stderr)
        sys.exit(1)

    res = run_security_arm(match, args.arm, Path(args.output_dir))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
