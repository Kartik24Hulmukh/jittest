"""WO-17 Harness: Run a single benchmark instance across pre-registered arms A-E.

Pre-registered arms (IMMUTABLE — see WO-17 pre-registration):
  A  gold     gold patch applied                  -> expect reproduction_catch
  B  comment  comment-only patch                  -> expect NOT a catch
  C  crossed  gold patch of a DIFFERENT instance
              whose "repo" field is the same      -> expect NOT a catch
              (false-proof control; primary source of FCR)
  D  timeout  gold patch + --timeout 1            -> probes exit-code path
  E  p2p      gold patch + PASS_TO_PASS           -> expect non_discriminating

IMPORTANT — This run is NOT the pre-registered in-container protocol and its
results may not be compared to the WO-17 decision gates.

The pre-registered protocol specifies in-container execution using
swebench/sweb.eval.x86_64.<instance_id_lower>:latest, container python at
/opt/miniconda3/envs/testbed/bin/python, testbed path /testbed. This workflow
runs bare on ubuntu-latest with pip install -e . which is a different
environment and cannot be used to adjudicate the WO-17 FCR gate.

Security arms (forged, unsandboxed) are in security-arms.yml and are NOT
part of the WO-17 pre-registration.
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
from jittest.verify import VerdictClass, verify_test

# Crossed-arm donor pairings: each instance_id maps to the donor instance_id
# whose gold patch will be applied (donor must share the same repo field).
# Derived from eval/swebench_lite_20.json with circular next-in-group assignment.
# Command: python -c "import json; ..."  (see WO-20-REPORT.md for full derivation)
CROSSED_DONOR: dict[str, str] = {
    "pallets__flask-4045": "pallets__flask-4992",
    "pallets__flask-4992": "pallets__flask-5063",
    "pallets__flask-5063": "pallets__flask-4045",
    "psf__requests-1963": "psf__requests-2148",
    "psf__requests-2148": "psf__requests-2317",
    "psf__requests-2317": "psf__requests-2674",
    "psf__requests-2674": "psf__requests-3362",
    "psf__requests-3362": "psf__requests-863",
    "psf__requests-863": "psf__requests-1963",
    "pytest-dev__pytest-11143": "pytest-dev__pytest-11148",
    "pytest-dev__pytest-11148": "pytest-dev__pytest-5103",
    "pytest-dev__pytest-5103": "pytest-dev__pytest-5221",
    "pytest-dev__pytest-5221": "pytest-dev__pytest-5227",
    "pytest-dev__pytest-5227": "pytest-dev__pytest-5413",
    "pytest-dev__pytest-5413": "pytest-dev__pytest-5495",
    "pytest-dev__pytest-5495": "pytest-dev__pytest-5692",
    "pytest-dev__pytest-5692": "pytest-dev__pytest-6116",
    "pytest-dev__pytest-6116": "pytest-dev__pytest-7168",
    "pytest-dev__pytest-7168": "pytest-dev__pytest-7220",
    "pytest-dev__pytest-7220": "pytest-dev__pytest-11143",
}


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


def _parse_fail_to_pass(instance: dict[str, Any]) -> list[str]:
    """Parse FAIL_TO_PASS which may be a JSON-encoded string or already a list."""
    raw = instance.get("FAIL_TO_PASS", [])
    if isinstance(raw, str):
        try:
            result = json.loads(raw)
            return result if isinstance(result, list) else []
        except (ValueError, TypeError):
            return []
    return raw if isinstance(raw, list) else []


def _build_test_path(repo_path: Path, test_node: str) -> str:
    """Build an absolute test_file_path string rooted in repo_path."""
    if "::" in test_node:
        file_part, node_part = test_node.split("::", 1)
        return str(repo_path / file_part) + "::" + node_part
    return str(repo_path / test_node)


def _apply_patch(repo_path: Path, patch_text: str) -> bool:
    """Apply a patch. Returns True on success."""
    p = Path(tempfile.mktemp(suffix=".patch"))
    p.write_bytes(patch_text.encode("utf-8"))
    res = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--ignore-whitespace", str(p)],
        capture_output=True,
        env=git_env(),
    )
    return res.returncode == 0


def _reset_repo(repo_path: Path, base_sha: str, branch_name: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo_path), "checkout", "--detach", base_sha],
        check=True, capture_output=True, env=git_env(),
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "reset", "--hard"],
        check=True, capture_output=True, env=git_env(),
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "checkout", "-B", branch_name],
        check=True, capture_output=True, env=git_env(),
    )
    for cfg in [("user.name", "test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false")]:
        subprocess.run(
            ["git", "-C", str(repo_path), "config"] + list(cfg),
            check=True, env=git_env(),
        )


def run_arm(
    instance: dict[str, Any],
    arm: str,
    output_dir: Path,
    all_instances: list[dict[str, Any]],
    sandbox_mode: str = "auto",
    timeout_override: int | None = None,
) -> dict[str, Any]:
    inst_id = instance["instance_id"]
    repo_full = instance["repo"]
    base_sha = instance["base_commit"]
    patch = instance.get("patch", "")
    test_patch = instance.get("test_patch", "")
    fail_to_pass = _parse_fail_to_pass(instance)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_artifact = output_dir / f"{inst_id}_{arm}_evidence.json"

    repo_path = resolve_repo(repo_full)
    branch_name = f"gauntlet_{arm}_{inst_id}_{int(time.time())}"
    _reset_repo(repo_path, base_sha, branch_name)

    test_node = fail_to_pass[0] if fail_to_pass else "tests/test_basic.py"
    abs_test_path = _build_test_path(repo_path, test_node)

    timeout_s = timeout_override if timeout_override is not None else 300

    if arm == "gold":
        # A: Apply gold patch (solution + test patch) -> expect reproduction_catch
        combined = patch + "\n" + test_patch
        if not _apply_patch(repo_path, combined):
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "patch_apply_failed"}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "gold head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, env=git_env(),
        ).stdout.strip()

    elif arm == "comment":
        # B: Comment-only patch -> expect NOT a catch
        # Apply a trivial comment to any file so there is a head commit
        first_py = next((f for f in sorted(repo_path.glob("**/*.py")) if not str(f).startswith(str(repo_path / ".git"))), None)
        if first_py is None:
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "no_python_file_found"}
        orig = first_py.read_text(encoding="utf-8", errors="replace")
        first_py.write_text("# WO-17 comment arm\n" + orig, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "comment arm"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, env=git_env(),
        ).stdout.strip()

    elif arm == "crossed":
        # C: Apply gold patch of a DIFFERENT instance with same repo
        donor_id = CROSSED_DONOR.get(inst_id)
        if donor_id is None:
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "no_crossed_donor"}
        donor = next((i for i in all_instances if i["instance_id"] == donor_id), None)
        if donor is None:
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "donor_not_in_manifest"}
        donor_patch = donor.get("patch", "") + "\n" + donor.get("test_patch", "")
        if not _apply_patch(repo_path, donor_patch):
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "crossed_patch_apply_failed",
                    "donor_instance_id": donor_id}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "crossed head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, env=git_env(),
        ).stdout.strip()
        # Arm C must include donor pairing in artifact
        crossed_donor_id = donor_id

    elif arm == "timeout":
        # D: Gold patch + PASS_TO_PASS + --timeout 1
        # Apply the gold patch at base then run with 1s timeout to probe exit-code path
        combined = patch + "\n" + test_patch
        if not _apply_patch(repo_path, combined):
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "patch_apply_failed"}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "timeout head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, env=git_env(),
        ).stdout.strip()
        timeout_s = 1  # Force 1s timeout per WO-17 spec

    elif arm == "p2p":
        # E: Gold patch + PASS_TO_PASS (no timeout override) -> expect non_discriminating
        combined = patch + "\n" + test_patch
        if not _apply_patch(repo_path, combined):
            return {"instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                    "disposition": "patch_apply_failed"}
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "p2p head"], check=True, capture_output=True, env=git_env())
        head_sha = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, env=git_env(),
        ).stdout.strip()

    else:
        raise ValueError(f"Unknown arm: {arm!r}")

    evidence, exit_code = verify_test(
        repo_path=repo_path,
        base_ref=base_sha,
        head_ref=head_sha,
        test_file_path=abs_test_path,
        output_path=out_artifact,
        timeout_s=timeout_s,
        sandbox_mode=sandbox_mode,
    )

    result: dict[str, Any] = {
        "instance_id": inst_id,
        "arm": arm,
        "verdict": evidence.get("verdict"),
        "disposition": evidence.get("disposition"),
        "proven_catch": evidence.get("proven_catch"),
        "catch_direction": evidence.get("catch_direction"),
        "exit_code": exit_code,
        "artifact": str(out_artifact),
    }
    if arm == "crossed":
        result["donor_instance_id"] = crossed_donor_id  # type: ignore[possibly-undefined]

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="WO-17 Gauntlet Instance Runner (arms A-E)")
    parser.add_argument("--manifest", default="eval/swebench_lite_20.json", help="Path to manifest")
    parser.add_argument("--instance-id", required=True, help="Instance ID to run")
    parser.add_argument(
        "--arm",
        choices=["gold", "comment", "crossed", "timeout", "p2p"],
        required=True,
        help="Arm A=gold B=comment C=crossed D=timeout E=p2p",
    )
    parser.add_argument("--output-dir", default="eval/gauntlet_results", help="Output directory")
    parser.add_argument("--sandbox-mode", default="auto", help="Sandbox mode")
    args = parser.parse_args()

    with open(args.manifest, encoding="utf-8") as fh:
        instances = json.load(fh)

    match = next((i for i in instances if i["instance_id"] == args.instance_id), None)
    if not match:
        print(f"Instance {args.instance_id} not found in {args.manifest}", file=sys.stderr)
        sys.exit(1)

    res = run_arm(match, args.arm, Path(args.output_dir), instances, sandbox_mode=args.sandbox_mode)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
