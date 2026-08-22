"""Run SWE-bench Lite Pilot (20 instances sampled from princeton-nlp/SWE-bench_Lite) for reproduction verification.

Provenance: Sampled from SWE-bench Lite.
Disclaimer: This is an internal self-selected evaluation, NOT a benchmark submission.
No external party has re-executed these results.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from jittest.diff import git_env
from jittest.verify import verify_test

SCRIPT_DIR = Path(__file__).resolve().parent.parent
MANIFEST_PATH = SCRIPT_DIR / "eval" / "swebench_lite_20.json"


def resolve_fixture_repo(repo_full: str) -> Path:
    repo_name = repo_full.split("/")[-1]
    target = Path.home() / ".cache" / "jittest" / "fixtures" / repo_name
    if not target.exists() or not (target / ".git").exists():
        print(f"Cloning {repo_full} into {target}...")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo_full}", str(target)], check=True)
    return target


def run_instance(inst: dict[str, Any]) -> dict[str, Any]:
    inst_id = inst["instance_id"]
    repo_full = inst["repo"]
    repo_path = resolve_fixture_repo(repo_full)
    base_sha = inst["base_commit"]
    patch = inst.get("patch", "")
    test_patch = inst.get("test_patch", "")
    fail_to_pass = inst.get("FAIL_TO_PASS", [])

    subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "test"], check=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@example.com"], check=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "config", "commit.gpgsign", "false"], check=True, env=git_env())

    branch_name = f"test_head_{inst_id}"
    subprocess.run(["git", "-C", str(repo_path), "checkout", "--detach", base_sha], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "reset", "--hard"], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "checkout", "-B", branch_name], check=True, capture_output=True, env=git_env())

    p = Path(tempfile.mktemp(suffix=".patch"))
    p.write_bytes((patch + "\n" + test_patch).encode("utf-8"))
    apply_res = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--ignore-whitespace", "--ignore-space-change", str(p)],
        capture_output=True,
        env=git_env(),
    )
    if apply_res.returncode != 0:
        return {
            "instance_id": inst_id,
            "repo": repo_full,
            "verdict": "inconclusive",
            "disposition": "patch_apply_failed",
            "proven_catch": False,
            "catch_direction": "none",
            "base_failure_kind": "none",
        }

    subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True, env=git_env())
    subprocess.run(["git", "-C", str(repo_path), "commit", "-m", f"head fix {inst_id}"], check=True, capture_output=True, env=git_env())
    head_sha = subprocess.check_output(["git", "-C", str(repo_path), "rev-parse", "HEAD"], text=True, env=git_env()).strip()

    test_rel = None
    if fail_to_pass:
        first_test = fail_to_pass[0]
        test_rel = first_test.split("::")[0].strip()
    if not test_rel or not (repo_path / test_rel).exists():
        for line in test_patch.splitlines():
            if line.startswith("diff --git a/") and "test" in line:
                test_rel = line.split("diff --git a/")[1].split()[0]
                break

    test_file = repo_path / (test_rel or "tests/test_basic.py")

    start_t = time.time()
    try:
        ev, rc = verify_test(
            repo_path=repo_path,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_file,
            sandbox_mode="off",
            timeout_s=60,
        )
        wall_s = round(time.time() - start_t, 2)
        return {
            "instance_id": inst_id,
            "repo": repo_full,
            "verdict": ev.get("verdict", "inconclusive"),
            "disposition": ev.get("disposition", "UNKNOWN"),
            "proven_catch": ev.get("proven_catch", False),
            "catch_direction": ev.get("catch_direction", "none"),
            "base_failure_kind": ev.get("base_failure_kind", "none"),
            "wall_clock_s": wall_s,
        }
    except Exception as e:
        return {
            "instance_id": inst_id,
            "repo": repo_full,
            "verdict": "inconclusive",
            "disposition": "env_setup_failed",
            "proven_catch": False,
            "catch_direction": "none",
            "base_failure_kind": "error",
            "error": str(e),
        }


def main():
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        instances = json.load(fh)

    print(f"=== RUNNING SWE-BENCH LITE PILOT ON {len(instances)} INSTANCES ===")
    results = []
    for i, inst in enumerate(instances, 1):
        inst_id = inst["instance_id"]
        repo = inst["repo"]
        print(f"[{i:2d}/{len(instances)}] Running {inst_id} ({repo})...", flush=True)
        res = run_instance(inst)
        results.append(res)
        print(f"       -> {res['verdict']} | {res['disposition']} (catch: {res['proven_catch']}, direction: {res['catch_direction']})", flush=True)

    repro_catches = sum(1 for r in results if r.get("verdict") == "reproduction_catch")
    print("\n" + "=" * 60)
    print("=== SWE-BENCH LITE PILOT SUMMARY ===")
    print("=" * 60)
    print(f"reproduction_catch: {repro_catches} / {len(instances)}")

    dispositions: dict[str, int] = {}
    for r in results:
        d = r.get("disposition", "UNKNOWN")
        dispositions[d] = dispositions.get(d, 0) + 1

    print("\nRefusals by Disposition:")
    for d, cnt in sorted(dispositions.items()):
        print(f"  {d:<32}: {cnt}")

    out_file = SCRIPT_DIR / "eval" / "swebench_lite_20_results.json"
    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "provenance": {
                    "dataset": "SWE-bench Lite (princeton-nlp/SWE-bench_Lite, 20 instances)",
                    "note": "This is an internal self-selected evaluation, NOT a benchmark submission. No external party has re-executed these results.",
                },
                "total": len(instances),
                "reproduction_catch": repro_catches,
                "results": results,
            },
            fh,
            indent=2,
        )
    print(f"\nWrote pilot results to {out_file}")


if __name__ == "__main__":
    main()
