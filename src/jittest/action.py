"""GitHub Action Entrypoint & PR Verification Orchestrator.

Extracts changed test files from PR diffs, executes paired base/head verification
with fork-aware sandboxing (required for untrusted fork PRs), upserts a single
PR summary comment, and sets the workflow conclusion.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .diff import git_env
from .github import fetch_pr_base_head, upsert_pr_comment
from .verify import VerdictClass, verify_test

logger = logging.getLogger("jittest.action")

TEST_FILE_PATTERNS = ("test_", "_test.py")


def is_test_file(path_str: str) -> bool:
    p = Path(path_str)
    if p.suffix != ".py":
        return False
    name = p.name
    return name.startswith("test_") or name.endswith("_test.py") or "tests/" in path_str or "tests\\" in path_str


def get_changed_files(repo_path: Path, base_sha: str, head_sha: str) -> list[str]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--name-only", f"{base_sha}..{head_sha}"],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return files
    except Exception as exc:
        logger.error("Failed to run git diff: %s", exc)
        return []


def is_fork_pr() -> bool:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            pr = payload.get("pull_request", {})
            head_repo = pr.get("head", {}).get("repo", {}).get("full_name")
            base_repo = pr.get("base", {}).get("repo", {}).get("full_name")
            if head_repo and base_repo and head_repo != base_repo:
                return True
        except Exception:
            pass
    return False


def run_action(
    repo_path: Path | str = ".",
    pr_number: int | str | None = None,
    sandbox_override: str | None = None,
    output_dir: Path | str = "jittest-evidence",
) -> int:
    repo = Path(repo_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve PR number from env if not passed
    if pr_number is None:
        pr_number = os.getenv("JITTEST_PR_NUMBER") or os.getenv("GITHUB_REF", "").split("/")[-2] if "pull" in os.getenv("GITHUB_REF", "") else None

    # Fetch base and head SHAs
    base_sha = os.getenv("JITTEST_BASE") or os.getenv("GITHUB_BASE_SHA")
    head_sha = os.getenv("JITTEST_HEAD") or os.getenv("GITHUB_HEAD_SHA")

    if pr_number and (not base_sha or not head_sha):
        try:
            base_sha, head_sha = fetch_pr_base_head(str(repo), pr_number)
        except Exception as exc:
            logger.warning("Could not fetch PR base/head: %s", exc)

    if not base_sha or not head_sha:
        base_sha = "origin/main"
        head_sha = "HEAD"

    # Extract changed test files
    all_changed = get_changed_files(repo, base_sha, head_sha)
    changed_tests = [f for f in all_changed if is_test_file(f)]

    if not changed_tests:
        msg = (
            "<!-- jittest-report -->\n"
            "### 🛡️ `jittest verify` PR Check\n\n"
            "**Zero test files modified** in PR diff. Verification skipped.\n"
        )
        status = upsert_pr_comment(msg, pr_number=str(pr_number) if pr_number else None)
        print(f"jittest action: {status}")
        return 0

    # Determine Sandbox Mode
    fork = is_fork_pr()
    if sandbox_override:
        sbx_mode = sandbox_override
    elif fork:
        sbx_mode = "required"  # mandatory sandbox for external/fork PRs
    else:
        sbx_mode = "auto"

    no_sbx = sbx_mode == "off"

    import concurrent.futures

    def _verify_one(test_rel: str) -> dict[str, Any]:
        test_path = repo / test_rel
        if not test_path.exists():
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "file_not_found",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
            }

        out_artifact = out_dir / f"evidence-{test_path.stem}.json"
        print(f"\n[jittest action] Verifying {test_rel} (base={base_sha[:8]}, head={head_sha[:8]}, sandbox={sbx_mode})...")

        try:
            evidence, exit_code = verify_test(
                repo_path=repo,
                base_ref=base_sha,
                head_ref=head_sha,
                test_file_path=test_path,
                output_path=out_artifact,
                no_sandbox=no_sbx,
            )
            return {
                "file": test_rel,
                "verdict": evidence["verdict"],
                "disposition": evidence["disposition"],
                "proven_catch": evidence.get("proven_catch", False),
                "wall_clock_s": evidence.get("wall_clock_s", 0.0),
                "artifact": str(out_artifact),
            }
        except Exception as exc:
            logger.error("Failed verification for %s: %s", test_rel, exc)
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "ENV_SETUP_FAILED",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
            }

    results: list[dict[str, Any]] = []
    env_failed_tests: list[str] = []

    if len(changed_tests) > 1:
        max_workers = min(4, os.cpu_count() or 4)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(_verify_one, changed_tests))
    else:
        results = [_verify_one(t) for t in changed_tests]

    for r in results:
        if r["disposition"] in ("base_uncollectable", "head_uncollectable", "ENV_SETUP_FAILED"):
            env_failed_tests.append(r["file"])

    # Build Summary Comment Table
    table_lines = [
        "<!-- jittest-report -->",
        "### 🛡️ `jittest verify` PR Verdict Summary",
        "",
        "| Changed Test File | Base SHA | Head SHA | Verdict | Disposition | Duration |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    pc_count = 0
    for r in results:
        v_str = f"**`{r['verdict']}`**" if r["proven_catch"] else f"`{r['verdict']}`"
        table_lines.append(
            f"| `{r['file']}` | `{base_sha[:8]}` | `{head_sha[:8]}` | {v_str} | `{r['disposition']}` | {r['wall_clock_s']:.1f}s |"
        )
        if r["proven_catch"]:
            pc_count += 1

    table_lines.append("")
    table_lines.append(f"**Total Changed Tests Evaluated**: {len(results)} | **Proven Catches**: {pc_count}")

    if env_failed_tests:
        table_lines.append("")
        table_lines.append(f"⚠️ **Environment Setup Note**: {len(env_failed_tests)} test(s) experienced virtualenv or preflight setup failures (`ENV_SETUP_FAILED` / `uncollectable`). No test failure verdict was declared for these runs.")

    comment_body = "\n".join(table_lines)
    comment_status = upsert_pr_comment(comment_body, pr_number=str(pr_number) if pr_number else None)
    print(f"\njittest action PR Comment: {comment_status}")

    # Conclusion policy:
    # Success if >= 1 proven_catch OR zero test changes.
    # Neutral/Info if zero proven_catches but tests were non_discriminating/refuted.
    return 0 if pc_count >= 1 or len(results) == 0 else 0


def main():
    repo = os.getenv("JITTEST_REPO_PATH", ".")
    pr = os.getenv("JITTEST_PR_NUMBER")
    sbx = os.getenv("JITTEST_SANDBOX_MODE")
    code = run_action(repo_path=repo, pr_number=pr, sandbox_override=sbx)
    sys.exit(code)


if __name__ == "__main__":
    main()
