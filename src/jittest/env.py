"""Environment Provisioning for worktree executions.

Detects project lockfiles/manifests, creates isolated virtual environments
keyed by sha256(repo_path + sha + lockfiles), provisions dependencies for
both base and head worktrees, and preflights environment readiness.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

__all__ = ["provision_environment", "get_venv_python", "EnvSetupError"]


class EnvSetupError(RuntimeError):
    """Raised when virtual environment creation, dependency installation, or preflight checks fail."""


def _hash_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _compute_lockfile_hash(worktree_dir: Path) -> str:
    h = hashlib.sha256()
    lockfiles = [
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "requirements_dev.txt",
        "test-requirements.txt",
        "setup.py",
        "setup.cfg",
        "Pipfile",
        "poetry.lock",
        "uv.lock",
    ]
    for filename in sorted(lockfiles):
        p = worktree_dir / filename
        if p.is_file():
            h.update(filename.encode("utf-8"))
            h.update(_hash_file(p).encode("utf-8"))

    req_dir = worktree_dir / "requirements"
    if req_dir.is_dir():
        for req_p in sorted(req_dir.glob("*.txt")):
            h.update(req_p.name.encode("utf-8"))
            h.update(_hash_file(req_p).encode("utf-8"))

    return h.hexdigest()


def get_venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"
    return py


def _preflight_environment(python_exe: Path, worktree_dir: Path) -> None:
    """Preflight check: verify python can import sys and pytest/unittest works."""
    try:
        res = subprocess.run(
            [str(python_exe), "-c", "import sys"],
            cwd=str(worktree_dir),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if res.returncode != 0:
            raise EnvSetupError(f"Preflight python import check failed:\nSTDERR:\n{res.stderr[-1000:]}")
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"Preflight python check exception: {exc}") from exc

    try:
        res_pytest = subprocess.run(
            [str(python_exe), "-m", "pytest", "--version"],
            cwd=str(worktree_dir),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if res_pytest.returncode != 0:
            raise EnvSetupError(f"Preflight pytest check failed:\nSTDERR:\n{res_pytest.stderr[-1000:]}")
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"Preflight pytest check exception: {exc}") from exc


def provision_environment(
    worktree_dir: Path | str,
    commit_sha: str,
    repo_path: Path | str,
    cache_root: Path | str | None = None,
) -> dict[str, Any]:
    """Provision an isolated virtual environment for a worktree.

    Returns:
        {
            "venv_dir": str,
            "python_path": str,
            "cached": bool,
            "cache_key": str,
            "lockfile_sha256": str,
        }

    Raises:
        EnvSetupError: If venv creation, pip install, or preflight check fails.
    """
    worktree = Path(worktree_dir).resolve()
    repo = Path(repo_path).resolve()

    lockfile_hash = _compute_lockfile_hash(worktree)
    cache_key_raw = f"{repo}:{commit_sha}:{lockfile_hash}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8")).hexdigest()[:16]

    cache_root = Path.home() / ".jittest" / "envs" if cache_root is None else Path(cache_root)

    venv_dir = cache_root / f"env_{cache_key}"
    python_exe = get_venv_python(venv_dir)

    if python_exe.exists():
        _preflight_environment(python_exe, worktree)
        return {
            "venv_dir": str(venv_dir),
            "python_path": str(python_exe),
            "cached": True,
            "cache_key": cache_key,
            "lockfile_sha256": lockfile_hash,
        }

    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    # Create virtualenv
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except Exception as exc:
        raise EnvSetupError(f"Failed to create venv at {venv_dir}: {exc}") from exc

    pip_exe = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("pip.exe" if sys.platform == "win32" else "pip")
    if not pip_exe.exists():
        raise EnvSetupError(f"pip executable not found in created venv: {pip_exe}")

    install_targets = []
    has_pyproject = (worktree / "pyproject.toml").exists()
    has_setup = (worktree / "setup.py").exists() or (worktree / "setup.cfg").exists()

    if has_pyproject or has_setup:
        # Install with dev/test extras if available, fallback to package
        install_targets.append(["-e", f"{worktree}[dev,test,tests]"])

    req_candidates = [
        worktree / "requirements.txt",
        worktree / "requirements-dev.txt",
        worktree / "requirements_dev.txt",
        worktree / "test-requirements.txt",
    ]
    req_dir = worktree / "requirements"
    if req_dir.is_dir():
        req_candidates.extend(sorted(req_dir.glob("*.txt")))

    for req_file in req_candidates:
        if req_file.is_file():
            install_targets.append(["-r", str(req_file)])

    # Ensure pytest is installed
    install_targets.append(["pytest"])

    for target in install_targets:
        try:
            res = subprocess.run(
                [str(pip_exe), "install", *target],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=600,
            )
            if res.returncode != 0:
                # Fallback for editable install with extras if extras syntax failed
                if target[0] == "-e" and "[dev,test,tests]" in target[1]:
                    res_fallback = subprocess.run(
                        [str(pip_exe), "install", "-e", str(worktree)],
                        cwd=str(worktree),
                        capture_output=True,
                        text=True,
                        errors="replace",
                        timeout=600,
                    )
                    if res_fallback.returncode != 0:
                        err_tail = res_fallback.stderr[-1000:] or res_fallback.stdout[-1000:]
                        raise EnvSetupError(f"pip install -e {worktree} failed loudly:\n{err_tail}")
                else:
                    err_tail = res.stderr[-1000:] or res.stdout[-1000:]
                    raise EnvSetupError(f"pip install {' '.join(target)} failed loudly:\n{err_tail}")
        except Exception as exc:
            if isinstance(exc, EnvSetupError):
                raise
            raise EnvSetupError(f"pip install exception for target {target}: {exc}") from exc

    # Preflight check after installation
    _preflight_environment(python_exe, worktree)

    return {
        "venv_dir": str(venv_dir),
        "python_path": str(python_exe),
        "cached": False,
        "cache_key": cache_key,
        "lockfile_sha256": lockfile_hash,
    }

