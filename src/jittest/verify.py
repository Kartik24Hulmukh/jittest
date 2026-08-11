"""Verification Engine v0.2: Real-Repo Environments, Sandbox by Default, Signed Receipts.

Usage:
    jittest verify --repo <path> --base <sha> --head <sha> --test <file> [--path <dir>] [--no-sandbox]
    jittest verify --repo <owner/repo> --pr <number> --test <file>

Executes test files across paired base and head commits using isolated git
worktrees, provisioned per-commit virtualenvs, container/namespace sandboxing,
and Ed25519-signed evidence JSON artifacts.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any

from .diff import git_env
from .env import EnvSetupError, provision_environment
from .execute import Disposition, Outcome, Worktree, resolve_revision, run_test
from .github import fetch_pr_base_head
from .receipt import sign_evidence
from .sandbox import plan as plan_sandbox

__all__ = ["verify_test", "VerdictClass"]

logger = logging.getLogger("jittest.verify")


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
    base_ref: str | None = None,
    head_ref: str | None = None,
    test_file_path: Path | str | None = None,
    pr_number: int | str | None = None,
    rel_path: str = ".",
    output_path: Path | str | None = None,
    timeout_s: int = 60,
    reruns: int = 2,
    no_sandbox: bool = False,
    signing_key_path: Path | str | None = None,
) -> tuple[dict[str, Any], int]:
    """Run paired base/head verification and generate Ed25519 signed evidence artifact.

    Returns:
        (evidence_dict, exit_code)
        exit_code is 0 if verdict == 'proven_catch', 1 otherwise.
    """
    start_time = time.monotonic()
    repo_path = Path(repo_path).resolve()

    # Resolve PR if base/head not provided
    if pr_number is not None and (not base_ref or not head_ref):
        base_ref, head_ref = fetch_pr_base_head(str(repo_path), pr_number)

    if not base_ref or not head_ref:
        raise ValueError("Both base_ref and head_ref (or a valid --pr number) must be provided.")

    if test_file_path is None:
        raise ValueError("test_file_path must be provided.")

    test_path = Path(test_file_path).resolve()
    if not test_path.exists():
        raise FileNotFoundError(f"Test file not found: {test_path}")

    test_code = test_path.read_text(encoding="utf-8")
    test_file_sha256 = _hash_str(test_code)

    resolved_base = resolve_revision(repo_path, base_ref)
    resolved_head = resolve_revision(repo_path, head_ref)

    # Sandbox plan setup
    sandbox_mode = "off" if no_sandbox else "auto"
    if no_sandbox:
        logger.warning("WARNING: Sandbox disabled by user flag (--no-sandbox). Candidate tests will run unconfined.")

    sbx_plan = plan_sandbox(mode=sandbox_mode, probe=True)

    # Tool repository provenance
    tool_root = Path(__file__).resolve().parent.parent.parent
    tool_commit_sha = _get_git_sha(tool_root, "HEAD")
    tool_tree_sha = _get_git_sha(tool_root, "HEAD^{tree}")

    # 1. Provision HEAD environment & run on HEAD worktree
    try:
        with Worktree(repo_path, resolved_head) as head_dir:
            head_workdir = head_dir / rel_path if rel_path != "." else head_dir
            head_env_info = provision_environment(head_workdir, resolved_head, repo_path)
            head_python = head_env_info.get("python_path")
            head_run1 = run_test(head_workdir, test_code, timeout_s=timeout_s, sbx=sbx_plan, python_path=head_python)
    except EnvSetupError as exc:
        wall_clock_s = round(time.monotonic() - start_time, 4)
        evidence_dict = {
            "schema_version": "2.0",
            "tool": "jittest verify",
            "verdict": VerdictClass.INCONCLUSIVE,
            "proven_catch": False,
            "disposition": "env_setup_failed",
            "provenance": {
                "repo_path": str(repo_path),
                "base_sha": resolved_base,
                "head_sha": resolved_head,
                "test_file_name": test_path.name,
                "test_file_sha256": test_file_sha256,
                "tool_commit_sha": tool_commit_sha,
                "tool_tree_sha": tool_tree_sha,
                "rel_path": rel_path,
            },
            "sandbox": sbx_plan.as_dict(),
            "error": str(exc),
            "base_execution": {},
            "head_execution": {},
            "rerun_agreement": False,
            "wall_clock_s": wall_clock_s,
            "provider_cost_usd": 0.0,
        }
        signed_evidence = sign_evidence(evidence_dict, key_path=signing_key_path)
        if output_path is not None:
            out_p = Path(output_path).resolve()
            out_p.parent.mkdir(parents=True, exist_ok=True)
            out_p.write_text(json.dumps(signed_evidence, indent=2), encoding="utf-8")
        return signed_evidence, 1

    head_runs = [head_run1]

    # Rerun on HEAD if failed to check flakiness
    if head_run1.outcome is Outcome.FAIL and reruns > 1:
        try:
            with Worktree(repo_path, resolved_head) as head_dir:
                head_workdir = head_dir / rel_path if rel_path != "." else head_dir
                head_python = head_env_info.get("python_path")
                head_run2 = run_test(head_workdir, test_code, timeout_s=timeout_s, sbx=sbx_plan, python_path=head_python)
                head_runs.append(head_run2)
        except EnvSetupError as exc:
            pass

    rerun_agreement = len(head_runs) > 1 and (head_runs[0].outcome == head_runs[1].outcome) if len(head_runs) > 1 else True

    base_run = None
    base_env_info = None
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
        # 2. Provision BASE environment & run on BASE worktree
        try:
            with Worktree(repo_path, resolved_base) as base_dir:
                base_workdir = base_dir / rel_path if rel_path != "." else base_dir
                base_env_info = provision_environment(base_workdir, resolved_base, repo_path)
                base_python = base_env_info.get("python_path")
                base_run = run_test(base_workdir, test_code, timeout_s=timeout_s, sbx=sbx_plan, python_path=base_python)
        except EnvSetupError as exc:
            disposition = Disposition.BASE_UNCOLLECTABLE
            verdict_class = VerdictClass.INCONCLUSIVE
            exit_code = 1

        if base_run and base_run.outcome is Outcome.PASS:
            disposition = Disposition.CATCHING
            verdict_class = VerdictClass.PROVEN_CATCH
            is_proven_catch = True
            exit_code = 0
        elif base_run and base_run.outcome is Outcome.FAIL:
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
        "environment": base_env_info or {},
    }

    head_exec_dict = {
        "outcome": head_run1.outcome.name,
        "exit_code": head_run1.returncode,
        "stdout_sha256": _hash_str(head_run1.stdout),
        "stderr_sha256": _hash_str(head_run1.stderr),
        "environment": head_env_info or {},
    }

    evidence_dict: dict[str, Any] = {
        "schema_version": "2.0",
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
            "rel_path": rel_path,
        },
        "sandbox": sbx_plan.as_dict(),
        "base_execution": base_exec_dict,
        "head_execution": head_exec_dict,
        "rerun_agreement": rerun_agreement,
        "wall_clock_s": wall_clock_s,
        "provider_cost_usd": 0.0,
    }

    # Cryptographically sign the evidence dictionary with Ed25519 key
    signed_evidence = sign_evidence(evidence_dict, key_path=signing_key_path)

    if output_path is not None:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(signed_evidence, indent=2), encoding="utf-8")

    return signed_evidence, exit_code
