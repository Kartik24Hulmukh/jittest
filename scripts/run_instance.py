"""WO-17 Harness: Run a single benchmark instance across 5 experimental arms.

Arms:
  1. gold: test patch + solution patch -> expected reproduction_catch
  2. test_only: test patch only, no solution -> expected refuted / inconclusive
  3. empty: no changes -> expected non_discriminating
  4. forged: forged HMAC receipt -> expected verification rejection
  5. unsandboxed: sandbox required without container -> expected SANDBOX_UNAVAILABLE refusal
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from jittest.diff import git_env
from jittest.receipt import verify_receipt
from jittest.verify import VerdictClass, verify_test


def resolve_repo(repo_full: str, cache_dir: Path | None = None) -> Path:
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "jittest" / "fixtures"
    repo_name = repo_full.split("/")[-1]
    target = cache_dir / repo_name
    if not target.exists() or not (target / ".git").exists():
        print(f"Cloning {repo_full} into {target}...")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--quiet", f"https://github.com/{repo_full}", str(target)],
            check=True,
            env=git_env(),
        )
    return target


def run_arm(
    instance: dict[str, Any],
    arm: str,
    output_dir: Path,
    sandbox_mode: str = "auto",
) -> dict[str, Any]:
    inst_id = instance["instance_id"]
    repo_full = instance["repo"]
    base_sha = instance["base_commit"]
    patch = instance.get("patch", "")
    test_patch = instance.get("test_patch", "")
    fail_to_pass_raw = instance.get("FAIL_TO_PASS", [])
    # FAIL_TO_PASS may be a JSON-encoded string (e.g. '["tests/..."]') or already a list.
    if isinstance(fail_to_pass_raw, str):
        try:
            fail_to_pass = json.loads(fail_to_pass_raw)
        except (ValueError, TypeError):
            fail_to_pass = []
    else:
        fail_to_pass = fail_to_pass_raw

    output_dir.mkdir(parents=True, exist_ok=True)
    out_artifact = output_dir / f"{inst_id}_{arm}_evidence.json"

    # ARM 4: FORGED (receipt verification rejection test)
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

    repo_path = resolve_repo(repo_full)
    branch_name = f"gauntlet_{arm}_{inst_id}_{int(time.time())}"

    # Reset repository to clean base
    subprocess.run(["git", "-C", str(repo_path), "checkout", "--detach", base_sha], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "reset", "--hard"], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "checkout", "-B", branch_name], check=True, capture_output=True, env=git_env())

    # Configure git author
    subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "test"], check=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@example.com"], check=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "config", "commit.gpgsign", "false"], check=True, env=git_env())

    test_node = fail_to_pass[0] if fail_to_pass else "tests/test_basic.py"

    if arm == "gold":
        # Apply solution patch and gold test patch
        combined_patch = patch + "\n" + test_patch
        p = Path(tempfile.mktemp(suffix=".patch"))
        p.write_bytes(combined_patch.encode("utf-8"))
        res = subprocess.run(["git", "-C", str(repo_path), "apply", "--ignore-whitespace", str(p)], capture_output=True, env=git_env())
        if res.returncode != 0:
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive", "disposition": "patch_apply_failed"}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "gold head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, env=git_env()).stdout.strip()
    elif arm == "test_only":
        # Apply gold test patch ONLY (no solution patch)
        p = Path(tempfile.mktemp(suffix=".patch"))
        p.write_bytes(test_patch.encode("utf-8"))
        res = subprocess.run(["git", "-C", str(repo_path), "apply", "--ignore-whitespace", str(p)], capture_output=True, env=git_env())
        if res.returncode != 0:
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive", "disposition": "patch_apply_failed"}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "test only head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(["git", "-C", str(repo_path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True, env=git_env()).stdout.strip()
    elif arm in ("empty", "unsandboxed"):
        # No change
        head_sha = base_sha
    else:
        raise ValueError(f"Unknown arm: {arm}")

    # Build test_file_path: always use repo_path as the base so verify_test
    # resolves the test file within the target repo, not the jittest CWD.
    if "::" in test_node:
        file_part, node_part = test_node.split("::", 1)
        abs_test_path = str(repo_path / file_part) + "::" + node_part
    else:
        abs_test_path = str(repo_path / test_node)

    effective_sbx = "required" if arm == "unsandboxed" else sandbox_mode

    evidence, exit_code = verify_test(
        repo_path=repo_path,
        base_ref=base_sha,
        head_ref=head_sha,
        test_file_path=abs_test_path,
        output_path=out_artifact,
        sandbox_mode=effective_sbx,
    )

    return {
        "instance_id": inst_id,
        "arm": arm,
        "verdict": evidence.get("verdict"),
        "disposition": evidence.get("disposition"),
        "proven_catch": evidence.get("proven_catch"),
        "catch_direction": evidence.get("catch_direction"),
        "exit_code": exit_code,
        "artifact": str(out_artifact),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="WO-17 Gauntlet Instance Runner")
    parser.add_argument("--manifest", default="eval/swebench_lite_20.json", help="Path to manifest")
    parser.add_argument("--instance-id", required=True, help="Instance ID to run")
    parser.add_argument("--arm", choices=["gold", "test_only", "empty", "forged", "unsandboxed"], required=True)
    parser.add_argument("--output-dir", default="eval/gauntlet_results", help="Output directory")
    parser.add_argument("--sandbox-mode", default="auto", help="Sandbox mode")
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        instances = json.load(fh)

    match = next((i for i in instances if i["instance_id"] == args.instance_id), None)
    if not match:
        print(f"Instance {args.instance_id} not found in {args.manifest}", file=sys.stderr)
        sys.exit(1)

    res = run_arm(match, args.arm, Path(args.output_dir), sandbox_mode=args.sandbox_mode)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
