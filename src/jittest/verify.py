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
    - verdict: One of 'proven_catch' (regression catch: head fail + base pass),
      'reproduction_catch' (reproduction catch: base fail + head pass),
      'collection_catch' (collection catch: head uncollectable + base pass),
      'refuted' (head fail + base fail / latent), 'non_discriminating' (head pass),
      or 'inconclusive' (environment error, timeout, or base uncollectable).
    - catch_direction: One of 'regression' (for proven_catch), 'reproduction'
      (for reproduction_catch), or 'none' (for all other verdicts).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .diff import git_env
from .env import EnvSetupError, provision_environment
from .execute import (
    Disposition,
    FailureKind,
    Outcome,
    RunResult,
    Worktree,
    resolve_revision,
    run_test,
)
from .execution_paths import contained_execution_path, relative_execution_path
from .github import fetch_pr_base_head
from .receipt import get_repo_canonical, sign_evidence
from .sandbox import load_runtime_image, validate_image_ref
from .sandbox import plan as plan_sandbox

__all__ = [
    "verify_test",
    "VerdictClass",
    "VerifyRefusalError",
    "RefusalReason",
    "make_refusal_receipt",
    "get_repo_canonical",
    "exit_code_for",
    "catch_direction_for",
]

logger = logging.getLogger("jittest.verify")


@dataclass
class RefusalReason:
    code: str
    message: str = ""
    phase: str = "provision"
    details: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message or self.code,
            "phase": self.phase,
            "details": self.details,
        }


class VerifyRefusalError(ValueError):
    """A clean refusal for unusable verify inputs."""

    def __init__(self, message: str | RefusalReason, reason: RefusalReason | None = None) -> None:
        if isinstance(message, RefusalReason):
            self.reason = message
            super().__init__(message.message or message.code)
        elif reason is not None:
            self.reason = reason
            super().__init__(str(message))
        else:
            msg_str = str(message)
            code = msg_str
            if code.startswith("refused:"):
                code = code[len("refused:") :]
            self.reason = RefusalReason(code=code, message=msg_str)
            super().__init__(msg_str)


class VerdictClass:
    PROVEN_CATCH = "proven_catch"
    REPRODUCTION_CATCH = "reproduction_catch"
    COLLECTION_CATCH = "collection_catch"
    REFUTED = "refuted"
    NON_DISCRIMINATING = "non_discriminating"
    INCONCLUSIVE = "inconclusive"


def exit_code_for(verdict_class: str) -> int:
    """Return the exit code for a given verdict class.

    Only proven catches (regression or reproduction) exit 0.
    Everything else — including COLLECTION_CATCH — exits 1 (fail closed).
    """
    if verdict_class in (VerdictClass.PROVEN_CATCH, VerdictClass.REPRODUCTION_CATCH):
        return 0
    return 1


def catch_direction_for(verdict_class: str) -> str:
    """Return the catch direction for a given verdict class.

    'regression' for PROVEN_CATCH, 'reproduction' for REPRODUCTION_CATCH,
    'none' for everything else.
    """
    if verdict_class == VerdictClass.PROVEN_CATCH:
        return "regression"
    elif verdict_class == VerdictClass.REPRODUCTION_CATCH:
        return "reproduction"
    return "none"


def verdict_text_for(verdict_class: str) -> str:
    """Plain-language explanation for each public verdict label."""
    if verdict_class == VerdictClass.PROVEN_CATCH:
        return "Regression catch proven: the test passed on base and failed on head."
    if verdict_class == VerdictClass.REPRODUCTION_CATCH:
        return "Reproduction catch proven: the test failed on base and passed on head."
    if verdict_class == VerdictClass.COLLECTION_CATCH:
        return "Collection catch: head could not collect or execute while base passed."
    if verdict_class == VerdictClass.REFUTED:
        return "Refuted: the test failed on both base and head."
    if verdict_class == VerdictClass.NON_DISCRIMINATING:
        return "Non-discriminating: the test passed on both base and head."
    return "Inconclusive: verification refused because execution could not be completed safely."


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


def _write_json_atomically(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def make_refusal_receipt(
    repo_path: Path | str,
    base_ref: str = "HEAD~1",
    head_ref: str = "HEAD",
    test_file_path: Path | str | None = None,
    refusal: RefusalReason | dict[str, Any] | str = "sandbox_unavailable",
    sbx_plan: Any = None,
    signing_key_path: Path | str | None = None,
    output_path: Path | str | None = None,
    rel_path: str = ".",
) -> dict[str, Any]:
    """Generate and Ed25519-sign a schema 2.1 refusal receipt for unexecutable/untrusted runs."""
    repo = Path(repo_path).resolve()
    if isinstance(refusal, str):
        ref_obj = RefusalReason(code=refusal, message=refusal, phase="plan")
    elif isinstance(refusal, dict):
        ref_obj = RefusalReason(
            code=refusal.get("code", "unknown"),
            message=refusal.get("message", ""),
            phase=refusal.get("phase", "plan"),
            details=refusal.get("details", ""),
        )
    elif isinstance(refusal, RefusalReason):
        ref_obj = refusal
    else:
        ref_obj = RefusalReason(code="unknown", message=str(refusal), phase="plan")

    test_file_name = ""
    test_file_sha = _hash_str("")
    if test_file_path is not None:
        t_path = Path(test_file_path)
        test_file_name = t_path.name
        if t_path.exists() and t_path.is_file():
            with contextlib.suppress(Exception):
                test_file_sha = _hash_str(t_path.read_text(encoding="utf-8"))

    tool_root = Path(__file__).resolve().parent.parent.parent
    tool_commit_sha = _get_git_sha(tool_root, "HEAD")
    tool_branch = _get_git_branch(tool_root)
    tool_dirty = _get_git_dirty(tool_root)
    tool_tree_sha = _get_git_sha(tool_root, "HEAD^{tree}")

    resolved_base = resolve_revision(repo, base_ref) or base_ref
    resolved_head = resolve_revision(repo, head_ref) or head_ref
    repo_canonical = get_repo_canonical(repo)

    if sbx_plan is None:
        sbx_plan = plan_sandbox("auto", probe=False)

    disposition_val = f"refused_{ref_obj.code}"

    receipt: dict[str, Any] = {
        "schema_version": "2.1",
        "tool": "jittest verify",
        "verdict": VerdictClass.INCONCLUSIVE,
        "verdict_text": verdict_text_for(VerdictClass.INCONCLUSIVE),
        "proven_catch": False,
        "catch_direction": "none",
        "base_reproduced": False,
        "base_failure_kind": "none",
        "disposition": disposition_val,
        "refusal": ref_obj.to_dict(),
        "exclude_newer_cutoff": None,
        "interpreter_version": None,
        "resolved_versions": None,
        "provenance": {
            "repo_path": re.sub(r"^[a-zA-Z]:/[Uu]sers/[^/]+", "<USER_DIR>", str(repo).replace("\\", "/")),
            "repo_canonical": repo_canonical,
            "base_sha": resolved_base,
            "head_sha": resolved_head,
            "test_file_name": test_file_name,
            "test_file_sha256": test_file_sha,
            "tool_commit_sha": tool_commit_sha,
            "tool_branch": tool_branch,
            "tool_dirty": tool_dirty,
            "tool_tree_sha": tool_tree_sha,
            "rel_path": str(rel_path).replace("\\", "/"),
        },
        "sandbox": sbx_plan.as_dict() if hasattr(sbx_plan, "as_dict") else {},
        "base_execution": {
            "outcome": "NOTRUN",
            "exit_code": -1,
            "stdout_sha256": _hash_str(""),
            "stderr_sha256": _hash_str(""),
            "environment": {},
        },
        "head_execution": {
            "outcome": "NOTRUN",
            "exit_code": -1,
            "stdout_sha256": _hash_str(""),
            "stderr_sha256": _hash_str(""),
            "environment": {},
        },
        "rerun_agreement": True,
        "wall_clock_s": 0.0,
        "provider_cost_usd": 0.0,
    }

    signed = sign_evidence(receipt, key_path=signing_key_path)
    if output_path is not None:
        out_p = Path(output_path).resolve()
        _write_json_atomically(out_p, signed)
    return signed


def _verify_pass_to_pass(
    repo_path: Path,
    resolved_base: str,
    resolved_head: str,
    rel_path: str | Path,
    rel_test: Path | str,
    base_python: str | Path | None,
    head_python: str | Path | None,
    sbx_plan: Any,
    timeout_s: int = 30,
    phase_records: list[dict[str, Any]] | None = None,
    base_env_info: dict[str, Any] | None = None,
    head_env_info: dict[str, Any] | None = None,
) -> bool:
    """PASS_TO_PASS guard: verify that the test environment is healthy and capable of executing tests.

    Checks:
    1. If pre-existing unmodified tests exist in the repo (other than candidate test),
       at least one unmodified test passes at both base and head.
    2. In all cases, a clean passing assertion probe executes and passes at both base and head.
    """
    if phase_records is None:
        phase_records = []
    try:
        res_b = subprocess.run(
            ["git", "-C", str(repo_path), "ls-tree", "-r", "--name-only", resolved_base],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        res_h = subprocess.run(
            ["git", "-C", str(repo_path), "ls-tree", "-r", "--name-only", resolved_head],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
            env=git_env(),
        )
        base_files = set(res_b.stdout.splitlines())
        head_files = set(res_h.stdout.splitlines())
        common = base_files & head_files
        test_candidates = [
            f
            for f in sorted(common)
            if (
                f.endswith(".py")
                and (Path(f).name.startswith("test_") or Path(f).name.endswith("_test.py"))
            )
            and str(Path(f)) != str(Path(rel_test))
            and Path(f).name != Path(rel_test).name
        ]
        for f in test_candidates:
            # Git paths are repository-relative; the runner uses the selected root.
            if not Path(f).is_relative_to(Path(rel_path)):
                continue
            health_test = Path(f).relative_to(Path(rel_path))
            b_blob = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", f"{resolved_base}:{f}"],
                capture_output=True,
                text=True,
                errors="replace",
                env=git_env(),
            ).stdout.strip()
            h_blob = subprocess.run(
                ["git", "-C", str(repo_path), "rev-parse", f"{resolved_head}:{f}"],
                capture_output=True,
                text=True,
                errors="replace",
                env=git_env(),
            ).stdout.strip()
            if b_blob and b_blob == h_blob:
                content = subprocess.run(
                    ["git", "-C", str(repo_path), "show", f"{resolved_base}:{f}"],
                    capture_output=True,
                    text=True,
                    errors="replace",
                    env=git_env(),
                ).stdout
                if content.strip():
                    with Worktree(repo_path, resolved_base) as b_dir:
                        b_workdir = contained_execution_path(b_dir, rel_path, directory=True)
                        b_res = _run_guarded_phase(
                            b_workdir,
                            content,
                            timeout_s=timeout_s,
                            sbx=sbx_plan,
                            phase="pass_to_pass_base", revision=resolved_base,
                            env_info=base_env_info, records=phase_records,
                            python_path=base_python,
                            rel_test_path=health_test,
                        )
                        if b_res.outcome is Outcome.PASS:
                            with Worktree(repo_path, resolved_head) as h_dir:
                                h_workdir = contained_execution_path(h_dir, rel_path, directory=True)
                                h_res = _run_guarded_phase(
                                    h_workdir,
                                    content,
                                    timeout_s=timeout_s,
                                    sbx=sbx_plan,
                                    phase="pass_to_pass_head", revision=resolved_head,
                                    env_info=head_env_info, records=phase_records,
                                    python_path=head_python,
                                    rel_test_path=health_test,
                                )
                                if h_res.outcome is Outcome.PASS:
                                    return True
    except VerifyRefusalError:
        raise
    except Exception as exc:
        logger.debug("Error checking pre-existing tests in pass_to_pass guard: %s", exc)

    # Fallback to runtime assertion probe
    probe_code = "def test_jittest_pass_to_pass_probe():\n    assert 1 + 1 == 2\n"
    try:
        with Worktree(repo_path, resolved_base) as b_dir:
            b_workdir = contained_execution_path(b_dir, rel_path, directory=True)
            b_res = _run_guarded_phase(
                b_workdir,
                probe_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                phase="probe_base", revision=resolved_base,
                env_info=base_env_info, records=phase_records,
                python_path=base_python,
            )
            if b_res.outcome is not Outcome.PASS:
                return False

        with Worktree(repo_path, resolved_head) as h_dir:
            h_workdir = contained_execution_path(h_dir, rel_path, directory=True)
            h_res = _run_guarded_phase(
                h_workdir,
                probe_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                phase="probe_head", revision=resolved_head,
                env_info=head_env_info, records=phase_records,
                python_path=head_python,
            )
            if h_res.outcome is not Outcome.PASS:
                return False
        return True
    except VerifyRefusalError:
        raise
    except Exception as exc:
        logger.warning("Pass-to-pass probe execution failed: %s", exc)
        return False


# --- P0 state-machine wiring (policy -> readiness -> run -> output guard -> integrity) ---
# These helpers put the previously library-only P0 modules on the public
# `jittest verify` path. Default posture is OBSERVE (record findings in the
# signed receipt); set JITTEST_READINESS=required / JITTEST_OUTPUT_GUARD=required
# to make them fail-closed refusals. Enforcement is opt-in until live-daemon
# evidence exists, so that an honest observation never becomes a false refusal.

READINESS_ENV = "JITTEST_READINESS"
OUTPUT_GUARD_ENV = "JITTEST_OUTPUT_GUARD"
_ENFORCING = ("required", "enforce", "1", "true")


def _p0_mode(var: str) -> str:
    return (os.environ.get(var) or "observe").strip().lower()


def _p0_error(mode: str, *, readiness: bool, reason: str) -> dict[str, Any]:
    """Observation may degrade; explicit enforcement must never fail open."""
    code = "environment_not_ready" if readiness else "output_boundary_violation"
    phase = "readiness" if readiness else "export"
    if mode in _ENFORCING:
        raise VerifyRefusalError(RefusalReason(code=code, message=reason, phase=phase))
    return {"evaluated" if readiness else "scanned": False, "mode": mode, "reason": reason}


def _read_readiness_file(path: Path) -> str | None:
    """Bounded, no-follow read of a quiescent worktree's optional manifest.

    Refuse special nodes before opening (including FIFOs), and compare the
    descriptor identity to lstat. This is not a live-writer sandbox primitive.
    """
    try:
        expected = path.lstat()
    except FileNotFoundError:
        return None
    limit = 200_000
    if not stat.S_ISREG(expected.st_mode) or expected.st_nlink != 1:
        raise ValueError("requirements_not_regular_single_link")
    if expected.st_size > limit:
        raise ValueError("requirements_too_large")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        with os.fdopen(fd, "rb") as handle:
            fd = -1
            before = os.fstat(handle.fileno())
            def identity(entry: os.stat_result) -> tuple[int, ...]:
                return (entry.st_dev, entry.st_ino, entry.st_mode, entry.st_nlink,
                        entry.st_size, entry.st_mtime_ns, entry.st_ctime_ns)
            if identity(before)[:5] != identity(expected)[:5]:
                raise ValueError("requirements_changed")
            data = handle.read(limit + 1)
            if len(data) > limit:
                raise ValueError("requirements_too_large")
            if (identity(before) != identity(os.fstat(handle.fileno()))
                    or identity(expected) != identity(path.lstat())):
                raise ValueError("requirements_changed")
            return data.decode("utf-8", errors="strict")
    finally:
        if fd != -1:
            os.close(fd)


def _readiness_block(workdir: Path | str, env_info: dict[str, Any] | None) -> dict[str, Any] | None:
    """Dependency-presence observation, not a complete resolver/ABI proof."""
    mode = _p0_mode(READINESS_ENV)
    try:
        from .readiness import evaluate_readiness, parse_requirements

        wd = Path(workdir)
        source = None
        text = None
        for name in ("requirements.txt", "requirements-dev.txt"):
            text = _read_readiness_file(wd / name)
            if text is not None:
                source = wd / name
                break
        if source is None or text is None:
            return None
        lock_text = _read_readiness_file(wd / "requirements.lock")
        resolved = (env_info or {}).get("resolved_versions") or []
        # provision_environment returns pip-freeze lines, not a version mapping.
        if isinstance(resolved, dict):
            target = set(resolved)
        elif isinstance(resolved, list) and all(isinstance(line, str) for line in resolved):
            target = {req.name for req in parse_requirements("\n".join(resolved))}
        else:
            raise ValueError("invalid_resolved_versions")
        report = evaluate_readiness(text, target, lock_text=lock_text)
    except Exception as exc:
        return _p0_error(mode, readiness=True, reason=f"readiness_error:{type(exc).__name__}")
    block = {
        "evaluated": True,
        "mode": mode,
        "source": source.name,
        "ok": bool(report.ok),
        "problems": list(report.problems)[:50],
    }
    if not report.ok and mode in _ENFORCING:
        raise VerifyRefusalError(
            RefusalReason(
                code="environment_not_ready",
                message="target runtime cannot satisfy declared dependencies",
                phase="readiness",
                details="; ".join(list(report.problems)[:10]),
            )
        )
    return block


def _output_guard_block(workdir: Path | str) -> dict[str, Any] | None:
    """Inspect the quiescent candidate tree after execution has stopped."""
    mode = _p0_mode(OUTPUT_GUARD_ENV)
    try:
        from .outputguard import OutputLimits, scan_output_tree
    except Exception as exc:  # pragma: no cover - import guard
        return _p0_error(mode, readiness=False, reason=f"scan_import_error:{type(exc).__name__}")
    try:
        limits = OutputLimits(max_bytes=2 * 1024 * 1024 * 1024, max_files=200_000, max_entries=200_000)
        scan = scan_output_tree(workdir, limits=limits)
    except Exception as exc:
        return _p0_error(mode, readiness=False, reason=f"scan_error:{type(exc).__name__}")
    block = {
        "scanned": True,
        "mode": mode,
        "ok": bool(scan.ok),
        "files": int(scan.files),
        "total_bytes": int(scan.total_bytes),
        "violations": list(scan.violations)[:50],
    }
    if not scan.ok and mode in _ENFORCING:
        raise VerifyRefusalError(
            RefusalReason(
                code="output_boundary_violation",
                message="candidate output tree violated the export boundary",
                phase="export",
                details="; ".join(list(scan.violations)[:10]),
            )
        )
    return block


def _run_guarded_phase(
    workdir: Path | str,
    test_code: str,
    *,
    phase: str,
    revision: str,
    env_info: dict[str, Any] | None,
    records: list[dict[str, Any]],
    **run_kwargs: Any,
) -> RunResult:
    """Apply policy around each execution; observations are signed by the caller.

    Output inspection assumes the runner's quiescent-tree contract. It does not
    establish confinement for an unconfined execution or replace descendant cleanup.
    """
    record: dict[str, Any] = {"phase": phase, "revision": revision,
                              "test_sha256": _hash_str(test_code),
                              "dependencies_sha256": _hash_str(json.dumps(
                                  (env_info or {}).get("resolved_versions") or [],
                                  sort_keys=True, separators=(",", ":")))}
    records.append(record)
    try:
        record["readiness"] = _readiness_block(workdir, env_info) or {
            "evaluated": False, "mode": _p0_mode(READINESS_ENV),
            "reason": "no_supported_requirements_manifest",
        }
        result = run_test(Path(workdir), test_code, **run_kwargs)
        record.update(outcome=result.outcome.name, exit_code=result.returncode,
                      stdout_sha256=_hash_str(result.stdout),
                      stderr_sha256=_hash_str(result.stderr))
        record["output_guard"] = _output_guard_block(workdir)
        return result
    except VerifyRefusalError as exc:
        # Preserve typed policy refusals, including through health-probe fallbacks.
        record["refusal"] = exc.reason.to_dict()
        raise


def _integrity_block(
    *,
    test_code: str,
    sandbox_dict: dict[str, Any],
    env_info: dict[str, Any] | None,
    command: list[str],
    exit_code: int,
    output_material: str,
    incomplete: bool,
    non_reproducible: bool,
) -> dict[str, Any] | None:
    """integrity-1.0 binding, attached additively to the signed receipt."""
    try:
        from .integrity import build_integrity_record, canonical_json
    except Exception:  # pragma: no cover - import guard
        return None
    try:
        resolved = (env_info or {}).get("resolved_versions") or {}
        record = build_integrity_record(
            source_bytes=test_code.encode("utf-8", "replace"),
            image_digest=str(sandbox_dict.get("image_digest") or sandbox_dict.get("image") or ""),
            dependencies_text=canonical_json(resolved),
            policy_text=canonical_json(sandbox_dict),
            command=command,
            exit_code=int(exit_code),
            output_bytes=output_material.encode("utf-8", "replace"),
            incomplete=bool(incomplete),
            non_reproducible=bool(non_reproducible),
        )
    except Exception as exc:
        return {"schema_version": "integrity-1.0", "error": f"integrity_error:{type(exc).__name__}"}
    payload = record.to_dict()
    payload["record_digest"] = record.digest()
    return payload


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
        exit_code is 0 if verdict in ('proven_catch', 'reproduction_catch'), 1 otherwise.
    """
    start_time = time.monotonic()
    repo_path = Path(repo_path).resolve()

    # Resolve PR if base/head not provided
    if pr_number is not None and (not base_ref or not head_ref):
        base_ref, head_ref = fetch_pr_base_head(str(repo_path), pr_number)

    if not base_ref or not head_ref:
        raise VerifyRefusalError("both base and head revisions are required")

    if test_file_path is None:
        raise VerifyRefusalError("test file path is required")

    node_id = None
    if isinstance(test_file_path, str) and "::" in test_file_path:
        file_part, node_id = test_file_path.split("::", 1)
        test_path = Path(file_part)
    else:
        test_path = Path(test_file_path)

    if not test_path.is_absolute():
        test_path = repo_path / test_path

    if not test_path.exists():
        raise VerifyRefusalError(f"test file not found: {test_path}")

    resolved_test = test_path.resolve()
    if not resolved_test.is_file():
        raise VerifyRefusalError(f"test path is not a regular file: {test_path}")

    try:
        if not resolved_test.is_relative_to(repo_path):
            raise VerifyRefusalError(f"test path is outside repository: {test_path}")
    except (ValueError, AttributeError):
        raise VerifyRefusalError(f"test path is outside repository: {test_path}") from None

    test_path = resolved_test
    test_code = test_path.read_text(encoding="utf-8")
    if not test_code.strip():
        raise VerifyRefusalError(f"test file is empty: {test_path}")
    test_file_sha256 = _hash_str(test_code)

    resolved_base = resolve_revision(repo_path, base_ref)
    resolved_head = resolve_revision(repo_path, head_ref)
    if not resolved_base:
        raise VerifyRefusalError(f"base revision not found: {base_ref}")
    if not resolved_head:
        raise VerifyRefusalError(f"head revision not found: {head_ref}")

    rel_path = str(relative_execution_path(rel_path))
    selected_root = repo_path / rel_path
    if not test_path.is_relative_to(selected_root):
        raise VerifyRefusalError(RefusalReason(
            code="unsafe_execution_path",
            message="candidate test is outside the selected subproject", phase="prepare",
        ))
    execution_test = test_path.relative_to(selected_root)

    # Sandbox plan setup
    if sandbox_mode is not None:
        effective_sandbox_mode = sandbox_mode.strip().lower()
    else:
        effective_sandbox_mode = "off" if no_sandbox else "auto"

    if effective_sandbox_mode == "off":
        logger.warning("WARNING: Sandbox disabled. Candidate tests will run unconfined.")

    # Only maintainer-controlled BASE configuration may select executable images.
    runtime_image, runtime_notes = load_runtime_image(repo_path, resolved_base)
    for note in runtime_notes:
        logger.warning("%s", note)
    if runtime_image:
        valid, _ = validate_image_ref(runtime_image)
        if not valid:
            raise VerifyRefusalError(RefusalReason(
                code="image_digest_required",
                message="BASE runtime image must be pinned by @sha256:<64 hex digits>",
                phase="plan",
            ))
    sbx_plan = plan_sandbox(mode=effective_sandbox_mode, probe=True,
                           runtime_image=runtime_image)

    if effective_sandbox_mode == "required" and getattr(sbx_plan, "backend", "none") == "none":
        raise VerifyRefusalError(
            RefusalReason(
                code="sandbox_unavailable",
                message="sandbox isolation required but unavailable",
                phase="plan",
                details="; ".join(getattr(sbx_plan, "notes", []) or []),
            )
        )

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

    rel_test = test_path.relative_to(repo_path)

    # P0 state-machine observations (readiness preflight / output boundary guard)
    phase_records: list[dict[str, Any]] = []

    # 1. ALWAYS provision and execute BASE first (never short-circuit)
    base_run = None
    base_env_info = None
    base_err = None
    try:
        with Worktree(repo_path, resolved_base) as base_dir:
            base_workdir = contained_execution_path(base_dir, rel_path, directory=True)
            base_env_info = provision_environment(base_workdir, resolved_base, repo_path, sbx_plan=sbx_plan)
            if getattr(sbx_plan, "backend", None) in ("docker", "podman", "bubblewrap") and base_env_info.get("has_project_dependencies") and base_env_info.get("provisioning") != "option_c_trusted_image":
                raise VerifyRefusalError("isolation contract cannot import project dependencies in container mode")
            base_python = base_env_info.get("python_path")
            base_run = _run_guarded_phase(
                base_workdir,
                test_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                phase="base", revision=resolved_base,
                env_info=base_env_info, records=phase_records,
                python_path=base_python,
                rel_test_path=execution_test,
                node_id=node_id,
            )
    except EnvSetupError as exc:
        base_err = exc

    # 2. Provision and execute HEAD second (never short-circuit)
    head_run1 = None
    head_env_info = None
    head_err = None
    try:
        with Worktree(repo_path, resolved_head) as head_dir:
            head_workdir = contained_execution_path(head_dir, rel_path, directory=True)
            head_env_info = provision_environment(head_workdir, resolved_head, repo_path, sbx_plan=sbx_plan)
            if getattr(sbx_plan, "backend", None) in ("docker", "podman", "bubblewrap") and head_env_info.get("has_project_dependencies") and head_env_info.get("provisioning") != "option_c_trusted_image":
                raise VerifyRefusalError("isolation contract cannot import project dependencies in container mode")
            head_python = head_env_info.get("python_path")
            head_run1 = _run_guarded_phase(
                head_workdir,
                test_code,
                timeout_s=timeout_s,
                sbx=sbx_plan,
                phase="head", revision=resolved_head,
                env_info=head_env_info, records=phase_records,
                python_path=head_python,
                rel_test_path=execution_test,
                node_id=node_id,
            )
    except EnvSetupError as exc:
        head_err = exc

    head_runs = [head_run1] if head_run1 else []
    rerun_agreement = True

    # Rerun on HEAD if failed to check flakiness
    if head_run1 and head_run1.outcome is Outcome.FAIL and reruns > 1 and not head_err:
        try:
            with Worktree(repo_path, resolved_head) as head_dir:
                head_workdir = contained_execution_path(head_dir, rel_path, directory=True)
                head_python = head_env_info.get("python_path") if head_env_info else None
                head_run2 = _run_guarded_phase(
                    head_workdir,
                    test_code,
                    timeout_s=timeout_s,
                    sbx=sbx_plan,
                    phase="head_rerun_2", revision=resolved_head,
                    env_info=head_env_info, records=phase_records,
                    python_path=head_python,
                    rel_test_path=execution_test,
                    node_id=node_id,
                )
                head_runs.append(head_run2)
        except EnvSetupError:
            pass
        rerun_agreement = len(head_runs) > 1 and (head_runs[0].outcome == head_runs[1].outcome)

    # Determine base_failure_kind (assertion | error | timeout | collection | none)
    if base_err is not None or base_run is None:
        base_failure_kind = "error"
    elif base_run.outcome is Outcome.TIMEOUT:
        base_failure_kind = "timeout"
    elif base_run.outcome is Outcome.ERROR:
        base_failure_kind = "collection"
    elif base_run.outcome is Outcome.FAIL:
        out_err = base_run.stdout + "\n" + base_run.stderr
        if any(
            err_kw in out_err
            for err_kw in (
                "ImportError",
                "ModuleNotFoundError",
                "SyntaxError",
                "PytestCollectionWarning",
                "CollectionError",
            )
        ):
            base_failure_kind = "collection"
        elif base_run.failure_kind == FailureKind.ASSERTION:
            base_failure_kind = "assertion"
        elif base_run.failure_kind == FailureKind.ERROR:
            base_failure_kind = "error"
        elif "AssertionError" in out_err or "\nassert " in out_err:
            base_failure_kind = "assertion"
        else:
            base_failure_kind = "error"
    elif base_run.outcome is Outcome.PASS:
        base_failure_kind = "none"
    else:
        base_failure_kind = "none"

    # Determine head_failure_kind (assertion | error | timeout | collection | none)
    if head_err is not None or head_run1 is None:
        head_failure_kind = "error"
    elif head_run1.outcome is Outcome.TIMEOUT:
        head_failure_kind = "timeout"
    elif head_run1.outcome is Outcome.ERROR:
        head_failure_kind = "collection"
    elif head_run1.outcome is Outcome.FAIL:
        out_err = head_run1.stdout + "\n" + head_run1.stderr
        if any(
            err_kw in out_err
            for err_kw in (
                "ImportError",
                "ModuleNotFoundError",
                "SyntaxError",
                "PytestCollectionWarning",
                "CollectionError",
            )
        ):
            head_failure_kind = "collection"
        elif head_run1.failure_kind == FailureKind.ASSERTION:
            head_failure_kind = "assertion"
        elif head_run1.failure_kind == FailureKind.ERROR:
            head_failure_kind = "error"
        elif "AssertionError" in out_err or "\nassert " in out_err:
            head_failure_kind = "assertion"
        else:
            head_failure_kind = "error"
    elif head_run1.outcome is Outcome.PASS:
        head_failure_kind = "none"
    else:
        head_failure_kind = "none"

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
    elif base_run.outcome is Outcome.PASS:
        if head_run1.outcome is Outcome.FAIL:
            if not rerun_agreement:
                disposition = Disposition.HEAD_FLAKY
                verdict_class = VerdictClass.INCONCLUSIVE
                is_proven_catch = False
                exit_code = 1
            else:
                disposition = Disposition.CATCHING
                verdict_class = VerdictClass.PROVEN_CATCH
                is_proven_catch = True
                exit_code = 0
        elif head_run1.outcome is Outcome.PASS:
            disposition = Disposition.HEAD_PASSED
            verdict_class = VerdictClass.NON_DISCRIMINATING
            is_proven_catch = False
            exit_code = 1
        elif head_run1.outcome in (Outcome.ERROR, Outcome.NOTRUN, Outcome.TIMEOUT):
            disposition = Disposition.HEAD_UNCOLLECTABLE_BASE_PASSED
            verdict_class = (
                VerdictClass.COLLECTION_CATCH
            )  # Split collection catch from behavioral catch
            is_proven_catch = False  # NEVER count collection breakage as a behavioral catch
            exit_code = 1
        else:
            disposition = Disposition.HEAD_NOTRUN
            verdict_class = VerdictClass.NON_DISCRIMINATING
            is_proven_catch = False
            exit_code = 1
    elif base_run.outcome is Outcome.FAIL:
        if head_run1.outcome is Outcome.PASS:
            # Candidate for reproduction_catch (bug fixed on head, caught at base)
            # Guard (a): The base failure must be an assertion failure or an exception from the code
            # under test during the test body, NOT a collection/import/syntax/env error.
            if base_failure_kind == "collection" or base_run.outcome in (
                Outcome.ERROR,
                Outcome.TIMEOUT,
                Outcome.NOTRUN,
            ):
                disposition = Disposition.BASE_UNCOLLECTABLE
                verdict_class = VerdictClass.INCONCLUSIVE
                is_proven_catch = False
                exit_code = 1
            else:
                # Guard (b): PASS_TO_PASS guard (at least one pre-existing or probe test passes at both base and head)
                pass_to_pass_ok = _verify_pass_to_pass(
                    repo_path=repo_path,
                    resolved_base=resolved_base,
                    resolved_head=resolved_head,
                    rel_path=rel_path,
                    rel_test=rel_test,
                    base_python=base_python,
                    head_python=head_python,
                    sbx_plan=sbx_plan,
                    timeout_s=min(timeout_s, 30),
                    phase_records=phase_records,
                    base_env_info=base_env_info, head_env_info=head_env_info,
                )
                if not pass_to_pass_ok:
                    disposition = Disposition.BASE_REPRODUCTION_FAILED
                    verdict_class = VerdictClass.INCONCLUSIVE
                    is_proven_catch = False
                    exit_code = 1
                else:
                    base_reproduced = True
                    disposition = Disposition.REPRODUCTION_CATCH
                    verdict_class = VerdictClass.REPRODUCTION_CATCH
                    is_proven_catch = True
                    exit_code = 0
        elif head_run1.outcome is Outcome.FAIL:
            disposition = Disposition.HEAD_FAILED_BASE_FAILED_LATENT
            if base_failure_kind == "assertion" and head_failure_kind == "assertion":
                verdict_class = VerdictClass.REFUTED
            else:
                verdict_class = VerdictClass.INCONCLUSIVE
            is_proven_catch = False
            exit_code = 1
        else:
            disposition = Disposition.BASE_REPRODUCTION_FAILED
            verdict_class = VerdictClass.INCONCLUSIVE
            is_proven_catch = False
            exit_code = 1
    else:  # base_run.outcome in (Outcome.ERROR, Outcome.NOTRUN, Outcome.TIMEOUT)
        disposition = Disposition.BASE_UNCOLLECTABLE
        verdict_class = VerdictClass.INCONCLUSIVE
        is_proven_catch = False
        exit_code = 1

    wall_clock_s = round(time.monotonic() - start_time, 4)

    catch_direction = catch_direction_for(verdict_class)
    exit_code = exit_code_for(verdict_class)

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
        "failure_kind": base_failure_kind,
        "exit_code": base_run.returncode if base_run else -1,
        "stdout_sha256": _hash_str(base_run.stdout) if base_run else _hash_str(""),
        "stderr_sha256": _hash_str(base_run.stderr) if base_run else _hash_str(""),
        "environment": base_env_dict,
    }

    head_exec_dict = {
        "outcome": head_run1.outcome.name if head_run1 else "NOTRUN",
        "failure_kind": head_failure_kind,
        "exit_code": head_run1.returncode if head_run1 else -1,
        "stdout_sha256": _hash_str(head_run1.stdout) if head_run1 else _hash_str(""),
        "stderr_sha256": _hash_str(head_run1.stderr) if head_run1 else _hash_str(""),
        "environment": head_env_dict,
    }

    evidence_dict: dict[str, Any] = {
        "schema_version": "2.1",
        "tool": "jittest verify",
        "verdict": verdict_class,
        "verdict_text": verdict_text_for(verdict_class),
        "proven_catch": is_proven_catch,
        "catch_direction": catch_direction,
        "base_reproduced": base_reproduced,
        "base_failure_kind": base_failure_kind,
        "disposition": disposition.value if hasattr(disposition, "value") else str(disposition),
        "refusal": None,
        "exclude_newer_cutoff": base_env_info.get("exclude_newer_cutoff") if base_env_info else None,
        "interpreter_version": base_env_info.get("interpreter_version") if base_env_info else None,
        "resolved_versions": base_env_info.get("resolved_versions") if base_env_info else None,
        "provenance": {
            "repo_path": re.sub(r"^[a-zA-Z]:/[Uu]sers/[^/]+", "<USER_DIR>", str(repo_path).replace("\\", "/")),
            "repo_canonical": get_repo_canonical(repo_path),
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

    # Additive, optional P0 blocks (schema 2.1 permits extra top-level objects).
    evidence_dict["verification_phases"] = phase_records
    # Preserve legacy aliases with their original, explicitly limited scope.
    for phase_record in phase_records:
        if phase_record["phase"] == "base" and phase_record.get("readiness", {}).get("reason") != "no_supported_requirements_manifest":
            evidence_dict["readiness"] = phase_record["readiness"]
        if phase_record["phase"] == "head" and "output_guard" in phase_record:
            evidence_dict["output_guard"] = phase_record["output_guard"]
    integrity_block = _integrity_block(
        test_code=test_code,
        sandbox_dict=evidence_dict["sandbox"] if isinstance(evidence_dict.get("sandbox"), dict) else {},
        env_info=base_env_info,
        command=["jittest", "verify", resolved_base, resolved_head, str(rel_test).replace(chr(92), "/")],
        exit_code=exit_code,
        output_material=str(base_exec_dict["stdout_sha256"]) + str(head_exec_dict["stdout_sha256"]),
        incomplete=(base_run is None or head_run1 is None),
        non_reproducible=(not rerun_agreement),
    )
    if integrity_block is not None:
        evidence_dict["integrity"] = integrity_block

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
        _write_json_atomically(out_p, signed_evidence)

    return signed_evidence, exit_code
