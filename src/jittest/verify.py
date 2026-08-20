"""Verification Engine v0.2: Real-Repo Environments, Sandbox by Default, Signed Receipts.

Usage:
    jittest verify --repo <path> --base <sha> --head <sha> --test <file> [--path <dir>] [--no-sandbox]
    jittest verify --repo <owner/repo> --pr <number> --test <file>

Executes test files across paired base and head commits using isolated git
worktrees, provisioned per-commit virtualenvs, container/namespace sandboxing,
and Ed25519-signed evidence JSON artifacts.

Evidence Receipt Schema Notes:
    - provenance.tool_dirty: A boolean indicating whether the tool source tree
      has uncommitted modifications at the time of execution. Scoped specifically
      to tool source files (["src", "eval", "tests", "scripts", "pyproject.toml"]),
      ignoring runtime receipts in docs/evidence/, caches, and virtual environments.
    - verdict: One of 'proven_catch' (behavioral catch: head fail + base pass),
      'collection_catch' (collection catch: head uncollectable + base pass),
      'refuted' (head fail + base fail / latent), 'non_discriminating' (head pass),
      or 'inconclusive' (environment error, timeout, or base uncollectable).
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
    COLLECTION_CATCH = "collection_catch"
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


def _get_git_branch(repo_path: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        return res.stdout.strip()
    except Exception:
        return ""


def _get_git_dirty(repo_path: Path) -> bool:
    """Check if the tool's source code tree is dirty (ignoring test artifacts/evidence/cache)."""
    try:
        res = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "status",
                "--porcelain",
                "--",
                "src",
                "eval",
                "tests",
                "scripts",
                "pyproject.toml",
            ],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        return bool(res.stdout.strip())
    except Exception:
        return False


def _hash_str(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def verify_test(
    repo_path: Path | str,
    base_ref: str | None = None,
    head_ref: str | None = None,
    test_file_path: Path | str | None = None,
    pr_number: int | str | None = None,
    rel_path: str = ".",
    kind: str = "bug",
    output_path: Path | str | None = None,
    timeout_s: int = 120,
    reruns: int = 2,
    no_sandbox: bool = False,
    sandbox_mode: str | None = None,
    signing_key_path: Path | str | None = None,
) -> tuple[dict[str, Any], int]:
    """Run paired base/head verification and generate Ed25519 signed evidence artifact.

    Returns:
        (evidence_dict, exit_code)
        exit_code is 0 if verdict in ('proven_catch', 'collection_catch'), 1 otherwise.
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
    if sandbox_mode is not None:
        effective_sandbox_mode = sandbox_mode.strip().lower()
    else:
        effective_sandbox_mode = "off" if no_sandbox else "auto"

    if effective_sandbox_mode == "off":
        logger.warning("WARNING: Sandbox disabled. Candidate tests will run unconfined.")

    sbx_plan = plan_sandbox(mode=effective_sandbox_mode, probe=True)

    # A silently degraded sandbox is more dangerous than an explicitly disabled one:
    # nobody chose it, so nobody knows to compensate. The artifact already records
    # this in sandbox.notes; say it out loud too.
    if effective_sandbox_mode != "off" and getattr(sbx_plan, "backend", None) == "none":
        for note in getattr(sbx_plan, "notes", []) or []:
            logger.warning("WARNING: sandbox isolation unavailable - %s", note)

    # Tool repository provenance (scoped strictly to tool source tree)
    tool_root = Path(__file__).resolve().parent.parent.parent
    tool_commit_sha = _get_git_sha(tool_root, "HEAD")
    tool_branch = _get_git_branch(tool_root)
    tool_dirty = _get_git_dirty(tool_root)
    tool_tree_sha = _get_git_sha(tool_root, "HEAD^{tree}")

    rel_test = None
    try:
        if test_path.is_relative_to(repo_path):
            rel_test = test_path.relative_to(repo_path)
    except (ValueError, AttributeError):
        pass
    if rel_test is None:
        rel_test = Path(test_path.name)

    # 1. ALWAYS provision and execute BASE first (never short-circuit)
    base_run = None
    base_env_info = None
    base_err = None
    try:
        with Worktree(repo_path, resolved_base) as base_dir:
            base_workdir = base_dir / rel_path if rel_path != "." else base_dir
            base_env_info = provision_environment(base_workdir, resolved_base, repo_path)
            base_python = base_env_info.get("python_path")
            base_run = run_test(
                base_workdir,
                test_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                python_path=base_python,
                rel_test_path=rel_test,
            )
    except EnvSetupError as exc:
        base_err = exc

    # 2. Provision and execute HEAD second (never short-circuit)
    head_run1 = None
    head_env_info = None
    head_err = None
    try:
        with Worktree(repo_path, resolved_head) as head_dir:
            head_workdir = head_dir / rel_path if rel_path != "." else head_dir
            head_env_info = provision_environment(head_workdir, resolved_head, repo_path)
            head_python = head_env_info.get("python_path")
            head_run1 = run_test(
                head_workdir,
                test_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                python_path=head_python,
                rel_test_path=rel_test,
            )
    except EnvSetupError as exc:
        head_err = exc

    head_runs = [head_run1] if head_run1 else []
    rerun_agreement = True

    # Rerun on HEAD if failed to check flakiness
    if head_run1 and head_run1.outcome is Outcome.FAIL and reruns > 1 and not head_err:
        try:
            with Worktree(repo_path, resolved_head) as head_dir:
                head_workdir = head_dir / rel_path if rel_path != "." else head_dir
                head_python = head_env_info.get("python_path") if head_env_info else None
                head_run2 = run_test(
                    head_workdir,
                    test_code,
                    timeout_s=timeout_s,
                    sbx=sbx_plan,
                    python_path=head_python,
                    rel_test_path=rel_test,
                )
                head_runs.append(head_run2)
        except EnvSetupError:
            pass
        rerun_agreement = len(head_runs) > 1 and (head_runs[0].outcome == head_runs[1].outcome)

    base_reproduced = bool(base_run is not None and base_run.outcome is Outcome.PASS)

    # Determine disposition and verdict
    disposition = Disposition.ENV_SETUP_FAILED
    verdict_class = VerdictClass.INCONCLUSIVE
    is_proven_catch = False
    exit_code = 1

    if base_err is not None or head_err is not None or base_run is None or head_run1 is None:
        err_text = str(base_err or head_err or "")
        if "env_build_timeout" in err_text:
            disposition = Disposition.ENV_BUILD_TIMEOUT
        else:
            disposition = Disposition.ENV_SETUP_FAILED
        verdict_class = VerdictClass.INCONCLUSIVE
        is_proven_catch = False
        exit_code = 1
    elif not base_reproduced:
        # If base_reproduced is false, verdict MUST be "inconclusive" and disposition "base_reproduction_failed"
        # for both bug and control rows. No row may be scored refuted or proven_catch if base reproduction failed.
        disposition = Disposition.BASE_REPRODUCTION_FAILED
        verdict_class = VerdictClass.INCONCLUSIVE
        is_proven_catch = False
        exit_code = 1
    elif head_run1.outcome is Outcome.PASS:
        disposition = Disposition.HEAD_PASSED
        verdict_class = VerdictClass.NON_DISCRIMINATING
        is_proven_catch = False
        exit_code = 1
    elif not rerun_agreement:
        disposition = Disposition.HEAD_FLAKY
        verdict_class = VerdictClass.INCONCLUSIVE
        is_proven_catch = False
        exit_code = 1
    elif head_run1.outcome is Outcome.FAIL:
        if base_run.outcome is Outcome.PASS:
            disposition = Disposition.CATCHING
            verdict_class = VerdictClass.PROVEN_CATCH
            is_proven_catch = True
            exit_code = 0
        elif base_run.outcome is Outcome.FAIL:
            disposition = Disposition.HEAD_FAILED_BASE_FAILED_LATENT
            verdict_class = VerdictClass.REFUTED
            is_proven_catch = False
            exit_code = 1
        else:
            disposition = Disposition.BASE_UNCOLLECTABLE
            verdict_class = VerdictClass.INCONCLUSIVE
            is_proven_catch = False
            exit_code = 1
    else:  # head_run1.outcome in (Outcome.ERROR, Outcome.NOTRUN, Outcome.TIMEOUT)
        if base_run.outcome is Outcome.PASS:
            disposition = Disposition.HEAD_UNCOLLECTABLE_BASE_PASSED
            verdict_class = VerdictClass.COLLECTION_CATCH  # Split collection catch from behavioral catch
            is_proven_catch = False  # NEVER count collection breakage as a behavioral catch
            exit_code = 0
        else:
            disposition = Disposition.HEAD_UNCOLLECTABLE_BASE_BROKEN
            verdict_class = VerdictClass.INCONCLUSIVE
            is_proven_catch = False
            exit_code = 1

    wall_clock_s = round(time.monotonic() - start_time, 4)

    base_env_dict = {
        k: str(v).replace("\\", "/") if isinstance(v, (str, Path)) else v
        for k, v in (base_env_info or {}).items()
    }
    head_env_dict = {
        k: str(v).replace("\\", "/") if isinstance(v, (str, Path)) else v
        for k, v in (head_env_info or {}).items()
    }

    base_exec_dict = {
        "outcome": base_run.outcome.name if base_run else "NOTRUN",
        "exit_code": base_run.returncode if base_run else -1,
        "stdout_sha256": _hash_str(base_run.stdout) if base_run else _hash_str(""),
        "stderr_sha256": _hash_str(base_run.stderr) if base_run else _hash_str(""),
        "environment": base_env_dict,
    }

    head_exec_dict = {
        "outcome": head_run1.outcome.name if head_run1 else "NOTRUN",
        "exit_code": head_run1.returncode if head_run1 else -1,
        "stdout_sha256": _hash_str(head_run1.stdout) if head_run1 else _hash_str(""),
        "stderr_sha256": _hash_str(head_run1.stderr) if head_run1 else _hash_str(""),
        "environment": head_env_dict,
    }

    evidence_dict: dict[str, Any] = {
        "schema_version": "2.0",
        "tool": "jittest verify",
        "verdict": verdict_class,
        "proven_catch": is_proven_catch,
        "base_reproduced": base_reproduced,
        "disposition": disposition.value if hasattr(disposition, "value") else str(disposition),
        "exclude_newer_cutoff": base_env_info.get("exclude_newer_cutoff") if base_env_info else None,
        "interpreter_version": base_env_info.get("interpreter_version") if base_env_info else None,
        "resolved_versions": base_env_info.get("resolved_versions") if base_env_info else None,
        "provenance": {
            "repo_path": str(repo_path).replace("\\", "/"),
            "base_sha": resolved_base,
            "head_sha": resolved_head,
            "test_file_name": test_path.name,
            "test_file_sha256": test_file_sha256,
            "tool_commit_sha": tool_commit_sha,
            "tool_branch": tool_branch,
            "tool_dirty": tool_dirty,
            "tool_tree_sha": tool_tree_sha,
            "rel_path": str(rel_path).replace("\\", "/"),
        },
        "sandbox": sbx_plan.as_dict(),
        "base_execution": base_exec_dict,
        "head_execution": head_exec_dict,
        "rerun_agreement": rerun_agreement,
        "wall_clock_s": wall_clock_s,
        "provider_cost_usd": 0.0,
    }

    if base_err is not None or head_err is not None:
        err_msgs = []
        if base_err:
            err_msgs.append(f"base: {base_err}")
        if head_err:
            err_msgs.append(f"head: {head_err}")
        evidence_dict["error"] = "; ".join(err_msgs)

    # Cryptographically sign the evidence dictionary with Ed25519 key
    signed_evidence = sign_evidence(evidence_dict, key_path=signing_key_path)

    if output_path is not None:
        out_p = Path(output_path).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(signed_evidence, indent=2), encoding="utf-8")

    return signed_evidence, exit_code
