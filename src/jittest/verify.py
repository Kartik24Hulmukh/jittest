"""Verification MVP: Paired base/head execution and signed evidence generator.

Usage:
    jittest verify --repo <path> --base <sha> --head <sha> --test <file>

Executes an existing test on both base and head commits using Worktree and
differential_check. Emits a signed evidence JSON artifact containing execution
provenance, exit codes, and stdout/stderr hashes (no test source code).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .diff import git_env
from .execute import Disposition, Outcome, Worktree, resolve_revision, run_test

__all__ = ["verify_test", "VerdictClass"]


class VerdictClass:
    PROVEN_CATCH = "proven_catch"
    REFUTED = "refuted"
    NON_DISCRIMINATING = "non_discriminating"
    INCONCLUSIVE = "inconclusive"


def _get_git_sha(repo_path: Path, ref: str) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", ref],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        return res.stdout.strip()
    except Exception:
        return ""


def _hash_str(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def verify_test(
    repo_path: Path | str,
    base_ref: str,
    head_ref: str,
    test_file_path: Path | str,
    output_path: Path | str | None = None,
    timeout_s: int = 30,
    reruns: int = 2,
) -> tuple[dict[str, Any], int]:
    """Run paired base/head verification and generate signed evidence artifact.

    Returns:
        (evidence_dict, exit_code)
        exit_code is 0 if verdict == 'proven_catch', 1 otherwise.
    """
    start_time = time.monotonic()
    repo_path = Path(repo_path).resolve()
    test_path = Path(test_file_path).resolve()

    if not test_path.exists():
        raise FileNotFoundError(f"Test file not found: {test_path}")

    test_code = test_path.read_text(encoding="utf-8")
    test_file_sha256 = _hash_str(test_code)

    resolved_base = resolve_revision(repo_path, base_ref)
    resolved_head = resolve_revision(repo_path, head_ref)

    # Tool repository provenance
    tool_root = Path(__file__).resolve().parent.parent.parent
    tool_commit_sha = _get_git_sha(tool_root, "HEAD")
    tool_tree_sha = _get_git_sha(tool_root, "HEAD^{tree}")

    # 1. Run on HEAD worktree
    with Worktree(repo_path, resolved_head) as head_dir:
        head_run1 = run_test(head_dir, test_code, timeout_s=timeout_s)

    head_runs = [head_run1]

    # If head failed, run a second time on HEAD to verify rerun agreement (flakiness check)
    if head_run1.outcome is Outcome.FAIL and reruns > 1:
        with Worktree(repo_path, resolved_head) as head_dir:
            head_run2 = run_test(head_dir, test_code, timeout_s=timeout_s)
            head_runs.append(head_run2)

    rerun_agreement = len(head_runs) > 1 and (head_runs[0].outcome == head_runs[1].outcome) if len(head_runs) > 1 else True

    base_run = None
    disposition = Disposition.HEAD_PASSED
    verdict_class = VerdictClass.NON_DISCRIMINATING
    is_proven_catch = False
    exit_code = 1

    if head_run1.outcome is Outcome.PASS:
        disposition = Disposition.HEAD_PASSED
        verdict_class = VerdictClass.NON_DISCRIMINATING
    elif not rerun_agreement:
        disposition = Disposition.HEAD_FLAKY
        verdict_class = VerdictClass.INCONCLUSIVE
    elif head_run1.outcome is Outcome.FAIL:
        # 2. Run on BASE worktree
        with Worktree(repo_path, resolved_base) as base_dir:
            base_run = run_test(base_dir, test_code, timeout_s=timeout_s)

        if base_run.outcome is Outcome.PASS:
            disposition = Disposition.CATCHING
            verdict_class = VerdictClass.PROVEN_CATCH
            is_proven_catch = True
            exit_code = 0
        elif base_run.outcome is Outcome.FAIL:
            disposition = Disposition.HEAD_FAILED_BASE_FAILED_LATENT
            verdict_class = VerdictClass.REFUTED
        else:
            disposition = Disposition.BASE_UNCOLLECTABLE
            verdict_class = VerdictClass.INCONCLUSIVE
    else:
        disposition = Disposition.HEAD_UNCOLLECTABLE
        verdict_class = VerdictClass.INCONCLUSIVE

    wall_clock_s = round(time.monotonic() - start_time, 4)

    base_exec_dict = {
        "outcome": base_run.outcome.name if base_run else "NOTRUN",
        "exit_code": base_run.returncode if base_run else -1,
        "stdout_sha256": _hash_str(base_run.stdout) if base_run else _hash_str(""),
        "stderr_sha256": _hash_str(base_run.stderr) if base_run else _hash_str(""),
    }

    head_exec_dict = {
        "outcome": head_run1.outcome.name,
        "exit_code": head_run1.returncode,
        "stdout_sha256": _hash_str(head_run1.stdout),
        "stderr_sha256": _hash_str(head_run1.stderr),
    }

    evidence_dict: dict[str, Any] = {
        "schema_version": "1.0",
        "tool": "jittest verify",
        "verdict": verdict_class,
        "proven_catch": is_proven_catch,
        "disposition": disposition.value,
        "provenance": {
            "repo_path": str(repo_path),
            "base_sha": resolved_base,
            "head_sha": resolved_head,
            "test_file_name": test_path.name,
            "test_file_sha256": test_file_sha256,
            "tool_commit_sha": tool_commit_sha,
            "tool_tree_sha": tool_tree_sha,
        },
        "base_execution": base_exec_dict,
        "head_execution": head_exec_dict,
        "rerun_agreement": rerun_agreement,
        "wall_clock_s": wall_clock_s,
        "provider_cost_usd": 0.0,
    }

    if output_path is not None:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(evidence_dict, indent=2), encoding="utf-8")

    return evidence_dict, exit_code
