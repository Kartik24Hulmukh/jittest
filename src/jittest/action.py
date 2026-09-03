"""GitHub Action Entrypoint & PR Verification Orchestrator.

Extracts changed test files from PR diffs, executes paired base/head verification
with fork-aware sandboxing (required for untrusted fork PRs or unknown context),
upserts a single PR summary comment, and sets the workflow conclusion according
to the declared policy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .diff import git_env
from .github import fetch_pr_base_head, upsert_pr_comment
from .sandbox import SandboxUnavailable
from .verify import VerdictClass, verify_test

logger = logging.getLogger("jittest.action")

TEST_FILE_PATTERNS = ("test_", "_test.py")

REFUSAL_DISPOSITIONS = {
    "base_uncollectable",
    "head_uncollectable",
    "ENV_SETUP_FAILED",
    "SANDBOX_UNAVAILABLE",
    "TIMEOUT",
    "file_not_found",
    "base_reproduction_failed",
}


def is_test_file(path_str: str) -> bool:
    p = Path(path_str)
    if p.suffix != ".py":
        return False
    name = p.name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests/" in path_str
        or "tests\\" in path_str
    )


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


def get_trust_context() -> str:
    """Return 'fork', 'internal', or 'unknown' based on GitHub Actions event payload."""
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if event_path and os.path.exists(event_path):
        try:
            with open(event_path, encoding="utf-8") as fh:
                payload = json.load(fh)
            pr = payload.get("pull_request")
            if pr:
                head_repo = pr.get("head", {}).get("repo", {}).get("full_name")
                base_repo = pr.get("base", {}).get("repo", {}).get("full_name")
                if head_repo and base_repo:
                    return "fork" if head_repo != base_repo else "internal"
        except Exception as exc:
            logger.warning("Could not read GITHUB_EVENT_PATH: %s", exc)
    return "unknown"


def run_action(
    repo_path: Path | str = ".",
    pr_number: int | str | None = None,
    sandbox_override: str | None = None,
    policy: str | None = None,
    output_dir: Path | str = "jittest-evidence",
) -> int:
    repo = Path(repo_path).resolve()
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resolve policy
    policy_str = (
        policy or os.getenv("JITTEST_POLICY") or "advisory"
    ).strip().lower()
    if policy_str not in ("advisory", "strict", "block-on-refusal"):
        logger.warning("Unknown policy '%s'; falling back to 'advisory'", policy_str)
        policy_str = "advisory"

    # Resolve PR number from env if not passed
    if pr_number is None:
        pr_number = (
            os.getenv("JITTEST_PR_NUMBER")
            or (os.getenv("GITHUB_REF", "").split("/")[-2] if "pull" in os.getenv("GITHUB_REF", "") else None)
        )

    # Fetch base and head SHAs
    base_sha = os.getenv("JITTEST_BASE") or os.getenv("GITHUB_BASE_SHA")
    head_sha = os.getenv("JITTEST_HEAD") or os.getenv("GITHUB_HEAD_SHA")

    if pr_number and (not base_sha or not head_sha):
        try:
            base_sha, head_sha = fetch_pr_base_head(str(repo), pr_number)
        except Exception as exc:
            logger.warning("Could not fetch PR base/head: %s", exc)

    if not head_sha:
        try:
            head_sha = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True, errors="replace", env=git_env()
            ).strip()
        except Exception:
            head_sha = "HEAD"

    if not base_sha:
        for candidate_ref in ("origin/main", "origin/master", "main", "master"):
            try:
                res = subprocess.run(
                    ["git", "-C", str(repo), "merge-base", candidate_ref, head_sha],
                    capture_output=True, text=True, errors="replace", check=True, env=git_env()
                )
                cand_sha = res.stdout.strip()
                if cand_sha:
                    base_sha = cand_sha
                    break
            except Exception:
                continue
        if not base_sha:
            try:
                res = subprocess.run(
                    ["git", "-C", str(repo), "rev-parse", f"{head_sha}~1"],
                    capture_output=True, text=True, errors="replace", check=True, env=git_env()
                )
                base_sha = res.stdout.strip()
            except Exception:
                base_sha = "HEAD~1"

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

    # Determine Sandbox Mode:
    # Fork safety contract: untrusted fork PRs or unknown context MUST run with 'required'.
    # When sandbox-mode is 'auto', 'default', or unset:
    #   - 'fork' or 'unknown' context -> 'required'
    #   - 'internal' context -> 'auto'
    # Any explicit non-required mode (e.g. 'off') is disallowed for untrusted contexts.
    trust = get_trust_context()
    sbx_override = sandbox_override if sandbox_override is not None else os.getenv("JITTEST_SANDBOX_MODE")
    if sbx_override and sbx_override.strip() and sbx_override.strip().lower() not in ("auto", "default", ""):
        sbx_mode = sbx_override.strip().lower()
        if trust in ("fork", "unknown") and sbx_mode != "required":
            logger.warning(
                "Untrusted %s context cannot downgrade sandbox-mode '%s'; enforcing 'required'",
                trust,
                sbx_mode,
            )
            sbx_mode = "required"
    else:
        sbx_mode = "required" if trust in ("fork", "unknown") else "auto"

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

        posix_rel = Path(test_rel).as_posix()
        path_digest = hashlib.sha256(posix_rel.encode("utf-8")).hexdigest()[:12]
        out_artifact = out_dir / f"evidence-{test_path.stem}-{path_digest}.json"
        print(f"\n[jittest action] Verifying {test_rel} (base={base_sha[:8]}, head={head_sha[:8]}, sandbox={sbx_mode})...")

        try:
            evidence, exit_code = verify_test(
                repo_path=repo,
                base_ref=base_sha,
                head_ref=head_sha,
                test_file_path=test_path,
                output_path=out_artifact,
                sandbox_mode=sbx_mode,
            )
            return {
                "file": test_rel,
                "verdict": evidence["verdict"],
                "disposition": evidence["disposition"],
                "proven_catch": evidence.get("proven_catch", False),
                "wall_clock_s": evidence.get("wall_clock_s", 0.0),
                "artifact": str(out_artifact),
            }
        except SandboxUnavailable as exc:
            logger.error("Sandbox isolation required but unavailable: %s", exc)
            return {
                "file": test_rel,
                "verdict": VerdictClass.INCONCLUSIVE,
                "disposition": "SANDBOX_UNAVAILABLE",
                "proven_catch": False,
                "wall_clock_s": 0.0,
                "artifact": "",
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

    results: list[dict[str, Any]] = [_verify_one(t) for t in changed_tests]

    refusal_tests: list[dict[str, Any]] = [
        r for r in results if r["disposition"] in REFUSAL_DISPOSITIONS or r["verdict"] == VerdictClass.INCONCLUSIVE
    ]
    pc_count = sum(1 for r in results if r["proven_catch"])

    # Build Summary Comment Table
    table_lines = [
        "<!-- jittest-report -->",
        "### 🛡️ `jittest verify` PR Verdict Summary",
        "",
        "| Changed Test File | Base SHA | Head SHA | Verdict | Disposition | Duration | Artifact |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in results:
        v_str = f"**`{r['verdict']}`**" if r["proven_catch"] else f"`{r['verdict']}`"
        art_str = f"`{Path(r['artifact']).name}`" if r.get("artifact") else "-"
        table_lines.append(
            f"| `{r['file']}` | `{base_sha[:8]}` | `{head_sha[:8]}` | {v_str} | `{r['disposition']}` | {r['wall_clock_s']:.1f}s | {art_str} |"
        )

    table_lines.append("")
    table_lines.append(
        f"**Total Changed Tests Evaluated**: {len(results)} | **Proven Catches**: {pc_count} | **Policy**: `{policy_str}`"
    )

    if refusal_tests:
        table_lines.append("")
        table_lines.append(
            f"⚠️ **Execution / Setup Note**: {len(refusal_tests)} test(s) experienced setup, sandbox, or collection refusals. No positive regression catch was declared."
        )

    comment_body = "\n".join(table_lines)
    comment_status = upsert_pr_comment(comment_body, pr_number=str(pr_number) if pr_number else None)
    print(f"\njittest action PR Comment: {comment_status}")

    # Honest policy exit codes:
    # 1. 'advisory': exit 0, emit visible warning annotations on refusals.
    # 2. 'strict': exit 0 only if pc_count >= 1 or zero tests changed; exit 1 otherwise.
    # 3. 'block-on-refusal': exit 1 if any refusal occurred; exit 0 otherwise.
    if policy_str == "strict":
        if len(results) == 0 or pc_count >= 1:
            return 0
        print("::error::jittest verify: strict policy failed — zero proven catches found", file=sys.stderr)
        return 1

    if policy_str == "block-on-refusal":
        if refusal_tests:
            print(
                f"::error::jittest verify: block-on-refusal failed — {len(refusal_tests)} test(s) encountered refusals",
                file=sys.stderr,
            )
            return 1
        return 0

    # policy == 'advisory'
    if refusal_tests:
        print(
            f"::warning::jittest verify: {len(refusal_tests)} test(s) encountered refusals/errors",
            file=sys.stderr,
        )
    return 0


def main():
    repo = os.getenv("JITTEST_REPO_PATH", ".")
    pr = os.getenv("JITTEST_PR_NUMBER")
    sbx = os.getenv("JITTEST_SANDBOX_MODE")
    policy = os.getenv("JITTEST_POLICY")
    out_dir = os.getenv("JITTEST_OUTPUT_DIR") or "jittest-evidence"
    code = run_action(
        repo_path=repo,
        pr_number=pr,
        sandbox_override=sbx,
        policy=policy,
        output_dir=out_dir,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()

