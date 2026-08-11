"""Environment Provisioning for worktree executions.

Detects project lockfiles/manifests, creates isolated virtual environments
keyed by sha256(repo_path + sha + lockfiles), and provisions dependencies for
both base and head worktrees.
"""

from __future__ import annotations

import contextlib
import hashlib
import subprocess
import sys
from pathlib import Path
from typing import Any

__all__ = ["provision_environment", "get_venv_python"]


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
        # Fallback to sys.executable if venv creation fails
        return {
            "venv_dir": "",
            "python_path": sys.executable,
            "cached": False,
            "cache_key": cache_key,
            "lockfile_sha256": lockfile_hash,
            "error": str(exc),
        }

    # Install dependencies if manifest/lockfiles present
    pip_exe = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("pip.exe" if sys.platform == "win32" else "pip")
    
    install_targets = []
    if (worktree / "pyproject.toml").exists() or (worktree / "setup.py").exists():
        install_targets.append(["-e", str(worktree)])
    elif (worktree / "requirements.txt").exists():
        install_targets.append(["-r", str(worktree / "requirements.txt")])

    for target in install_targets:
        if pip_exe.exists():
            with contextlib.suppress(Exception):
                subprocess.run(
                    [str(pip_exe), "install", "--no-build-isolation", *target],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=300,
                )

    return {
        "venv_dir": str(venv_dir),
        "python_path": str(python_exe),
        "cached": False,
        "cache_key": cache_key,
        "lockfile_sha256": lockfile_hash,
    }
