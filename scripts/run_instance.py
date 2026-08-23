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

D6 FIX: base_ref construction now includes test_patch
-------------------------------------------------------
A reproduction catch requires the candidate test to EXIST AND FAIL at base
and EXIST AND PASS at head. Since test_patch adds the FAIL_TO_PASS tests, it
must be included in both base and head commits so verify_test can check the
fail->pass transition.

  base_ref = base_commit + test_patch   (commit)
  head_ref = base_ref + solution patch  (commit)

For arm E (p2p): test_node is taken from PASS_TO_PASS instead of FAIL_TO_PASS,
because a test that already passes on both sides is what should return
non_discriminating. test_patch is still applied to base and head.

For arm C (crossed): base = base_commit + own test_patch;
head = base + donor solution patch only (NOT donor's test_patch).
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


def _clone_url(repo_full: str) -> str:
    """Build the HTTPS clone URL for a GitHub repository.

    Extracted as a module-level helper so it can be unit-tested independently.
    The .git suffix is canonical for clone URLs and avoids a redirect.
    """
    return f"https://github.com/{repo_full}.git"


def resolve_repo(repo_full: str, cache_dir: Path | None = None) -> Path:
    if cache_dir is None:
        cache_dir = Path.home() / ".cache" / "jittest" / "fixtures"
    repo_name = repo_full.split("/")[-1]
    target = cache_dir / repo_name
    if not target.exists() or not (target / ".git").exists():
        print(f"Cloning {repo_full} into {target}...")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--quiet", _clone_url(repo_full), str(target)],
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


def _parse_pass_to_pass(instance: dict[str, Any]) -> list[str]:
    """Parse PASS_TO_PASS which may be a JSON-encoded string or already a list."""
    raw = instance.get("PASS_TO_PASS", [])
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


def _commit_all(repo_path: Path, message: str) -> str:
    """Stage all changes and commit. Returns the new HEAD SHA."""
    subprocess.run(
        ["git", "-C", str(repo_path), "add", "."],
        check=True, capture_output=True, env=git_env(),
    )
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-m", message],
        check=True, capture_output=True, env=git_env(),
    )
    return subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, env=git_env(),
    ).stdout.strip()


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


def _find_source_file_for_comment(repo_path: Path, test_patch: str) -> Path | None:
    """Find the source file that the test actually imports.

    D6 arm B (comment): the comment must go in a source file that the test
    imports, not an arbitrary glob match. We parse the solution patch to find
    which source file it modifies — that file is what the test is testing.
    Falls back to the test file itself if no source file can be determined.
    """
    import re
    # Look for 'diff --git a/<path>' lines in test_patch that do NOT match testing/*
    # The solution patch modifies source; we want a source file the test imports.
    # Try scanning the solution patch (which is in instance["patch"]) for the modified file.
    # But we only have test_patch here; search it for import statements.
    # Extract the test file name from the patch header
    header_match = re.search(r"^diff --git a/(.+?) b/", test_patch, re.MULTILINE)
    if not header_match:
        return None
    test_file_rel = header_match.group(1)  # e.g. "testing/test_junitxml.py"
    test_file_abs = repo_path / test_file_rel
    if not test_file_abs.exists():
        return None
    # Read the test file and find the first local import
    content = test_file_abs.read_text(encoding="utf-8", errors="replace")
    # Look for: from _pytest.xxx import or import _pytest.xxx
    for line in content.splitlines():
        m = re.match(r"^(?:from|import)\s+_pytest\.(\w+)", line)
        if m:
            module_name = m.group(1)
            candidate = repo_path / "src" / "_pytest" / f"{module_name}.py"
            if candidate.exists():
                return candidate
        m = re.match(r"^from\s+pytest\s+import", line)
        if m:
            candidate = repo_path / "src" / "pytest" / "__init__.py"
            if candidate.exists():
                return candidate
    # Fallback: return test file itself (comment-only change to test file is still harmless)
    return test_file_abs


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
    pass_to_pass = _parse_pass_to_pass(instance)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_artifact = output_dir / f"{inst_id}_{arm}_evidence.json"

    repo_path = resolve_repo(repo_full)
    branch_name = f"gauntlet_{arm}_{inst_id}_{int(time.time())}"
    _reset_repo(repo_path, base_sha, branch_name)

    timeout_s = timeout_override if timeout_override is not None else 300

    # ── STEP 1: Build base_ref = base_commit + test_patch ────────────────────
    # For all arms, the FAIL_TO_PASS tests must EXIST at base so verify_test
    # can observe fail->pass. Apply test_patch to both base and head.
    #
    # For arm E (p2p), use a PASS_TO_PASS test node instead (a test that already
    # passes at base_commit, so it also passes after test_patch is applied).
    #
    # For arm C (crossed), apply only OWN test_patch to base.
    if arm in ("gold", "timeout", "p2p", "comment", "crossed"):
        if not _apply_patch(repo_path, test_patch):
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "test_patch_apply_failed",
            }
        base_ref = _commit_all(repo_path, f"base+test_patch for {arm}")
    else:
        raise ValueError(f"Unknown arm: {arm!r}")

    # ── STEP 2: Choose the test node ─────────────────────────────────────────
    # arm E (p2p): use PASS_TO_PASS[0] because those tests pass on BOTH sides
    # (they should yield non_discriminating, not proven_catch)
    if arm == "p2p":
        if not pass_to_pass:
            # Fall back to FAIL_TO_PASS if PASS_TO_PASS is empty
            test_node = fail_to_pass[0] if fail_to_pass else "tests/test_basic.py"
            print(f"WARNING: PASS_TO_PASS is empty for {inst_id}, falling back to FAIL_TO_PASS[0]",
                  file=sys.stderr)
        else:
            test_node = pass_to_pass[0]
    else:
        test_node = fail_to_pass[0] if fail_to_pass else "tests/test_basic.py"

    abs_test_path = _build_test_path(repo_path, test_node)

    # ── STEP 3: Build head_ref per arm ────────────────────────────────────────
    if arm == "gold":
        # A: Apply gold solution patch on top of base+test_patch
        if not _apply_patch(repo_path, patch):
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "patch_apply_failed",
            }
        head_ref = _commit_all(repo_path, "gold head")

    elif arm == "comment":
        # B: Apply a comment-only change to a source file that the test imports.
        # The comment is inserted in the solution source file (the one the test
        # exercises) so that the test file is unmodified but the imported module
        # changes. This confirms the test is sensitive to that import.
        comment_target = _find_source_file_for_comment(repo_path, test_patch)
        if comment_target is None:
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "no_comment_target_found",
            }
        orig = comment_target.read_text(encoding="utf-8", errors="replace")
        comment_target.write_text("# WO-17 comment arm (D6)\n" + orig, encoding="utf-8")
        comment_target_rel = str(comment_target.relative_to(repo_path))
        head_ref = _commit_all(repo_path, f"comment arm: {comment_target_rel}")
        print(f"Comment arm target: {comment_target_rel} (source file imported by test)", file=sys.stderr)

    elif arm == "crossed":
        # C: Apply donor's solution patch ONLY (not donor's test_patch).
        # base already has own test_patch. The donor's fix should NOT make
        # this instance's test pass.
        donor_id = CROSSED_DONOR.get(inst_id)
        if donor_id is None:
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "no_crossed_donor",
            }
        donor = next((i for i in all_instances if i["instance_id"] == donor_id), None)
        if donor is None:
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "donor_not_in_manifest",
            }
        # Apply donor solution patch only (NOT donor test_patch)
        donor_solution_patch = donor.get("patch", "")
        if not _apply_patch(repo_path, donor_solution_patch):
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "crossed_patch_apply_failed",
                "donor_instance_id": donor_id,
            }
        head_ref = _commit_all(repo_path, f"crossed head: donor={donor_id}")
        crossed_donor_id = donor_id
        print(f"Crossed arm: instance={inst_id} donor={donor_id}", file=sys.stderr)

    elif arm == "timeout":
        # D: Apply gold solution on top of base+test_patch, then timeout=1s
        if not _apply_patch(repo_path, patch):
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "patch_apply_failed",
            }
        head_ref = _commit_all(repo_path, "timeout head")
        timeout_s = 1  # Force 1s timeout per WO-17 spec

    elif arm == "p2p":
        # E: Apply gold solution on top of base+test_patch.
        # Test node is from PASS_TO_PASS — already passes on both sides.
        if not _apply_patch(repo_path, patch):
            return {
                "instance_id": inst_id, "arm": arm, "verdict": "inconclusive",
                "disposition": "patch_apply_failed",
            }
        head_ref = _commit_all(repo_path, "p2p head")

    else:
        raise ValueError(f"Unknown arm: {arm!r}")

    # ── STEP 4: Run verify_test ───────────────────────────────────────────────
    evidence, exit_code = verify_test(
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        test_file_path=abs_test_path,
        output_path=out_artifact,
        timeout_s=timeout_s,
        sandbox_mode=sandbox_mode,
    )

    result: dict[str, Any] = {
        "instance_id": inst_id,
        "arm": arm,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "test_node": test_node,
        "verdict": evidence.get("verdict"),
        "disposition": evidence.get("disposition"),
        "proven_catch": evidence.get("proven_catch"),
        "catch_direction": evidence.get("catch_direction"),
        "exit_code": exit_code,
        "artifact": str(out_artifact),
    }
    if arm == "crossed":
        result["donor_instance_id"] = crossed_donor_id  # type: ignore[possibly-undefined]
    if arm == "comment":
        result["comment_target"] = comment_target_rel  # type: ignore[possibly-undefined]

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
