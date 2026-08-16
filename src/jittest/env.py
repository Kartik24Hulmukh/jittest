"""Environment Provisioning for worktree executions.

Detects project lockfiles/manifests, creates isolated virtual environments
keyed by sha256(repo_path + sha + lockfiles), provisions dependencies for
both base and head worktrees, and preflights environment readiness.
"""

from __future__ import annotations

import configparser
import hashlib
import logging
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

__all__ = ["provision_environment", "get_venv_python", "ensure_worktree_fixes", "EnvSetupError"]

logger = logging.getLogger("jittest.env")


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
        "dev-requirements.txt",
        "test-requirements.txt",
        "requirements-test.txt",
        "setup.py",
        "setup.cfg",
        "tox.ini",
        "Pipfile",
        "poetry.lock",
        "uv.lock",
    ]
    for filename in sorted(lockfiles):
        p = worktree_dir / filename
        if p.is_file():
            h.update(filename.encode("utf-8"))
            h.update(_hash_file(p).encode("utf-8"))

    for sub in ["requirements", "tests/requirements"]:
        req_dir = worktree_dir / sub
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


def ensure_worktree_fixes(worktree: Path) -> None:
    """Ensure worktree has required dynamic files for repos like pytest."""
    pytest_mod_dir = worktree / "src" / "_pytest"
    if pytest_mod_dir.is_dir():
        v_file = pytest_mod_dir / "_version.py"
        if not v_file.exists():
            try:
                v_file.write_text('version = "9.2.0.dev"\nversion_tuple = (9, 2, 0, "dev")\n', encoding="utf-8")
            except OSError:
                pass


def _preflight_environment(python_exe: Path, worktree_dir: Path) -> None:
    """Preflight check: verify python can import sys and pytest works."""
    ensure_worktree_fixes(worktree_dir)

    import os
    env = dict(os.environ)
    src_dir = worktree_dir / "src"
    paths = [str(src_dir), str(worktree_dir)] if src_dir.is_dir() else [str(worktree_dir)]
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(paths + ([existing_pp] if existing_pp else []))

    try:
        res = subprocess.run(
            [str(python_exe), "-c", "import sys; import pytest"],
            cwd=str(worktree_dir),
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if res.returncode != 0:
            err_msg = res.stderr.strip() or res.stdout.strip()
            raise EnvSetupError(f"Preflight python & pytest import check failed:\nSTDERR:\n{err_msg[-1000:]}")
    except subprocess.TimeoutExpired as exc:
        raise EnvSetupError(f"env_build_timeout: preflight python import check timed out after 30s: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"Preflight python check exception: {exc}") from exc

    try:
        res_pytest = subprocess.run(
            [str(python_exe), "-m", "pytest", "--version"],
            cwd=str(worktree_dir),
            env=env,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if res_pytest.returncode != 0:
            err_msg = res_pytest.stderr.strip() or res_pytest.stdout.strip()
            raise EnvSetupError(f"Preflight pytest --version check failed:\nSTDERR:\n{err_msg[-1000:]}")
    except subprocess.TimeoutExpired as exc:
        raise EnvSetupError(f"env_build_timeout: preflight pytest --version check timed out after 30s: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"Preflight pytest check exception: {exc}") from exc


def _discover_extras_and_requirements(worktree: Path) -> tuple[list[str], list[Path]]:
    """Discover all test/dev extras, package specs, and requirement files."""
    packages: set[str] = set()
    req_files: list[Path] = []

    # 1. pyproject.toml discovery
    pyproject_path = worktree / "pyproject.toml"
    if pyproject_path.is_file():
        try:
            data = tomllib.loads(pyproject_path.read_text(encoding="utf-8", errors="replace"))

            # [project] dependencies (PEP 621 core dependencies)
            proj_deps = data.get("project", {}).get("dependencies", [])
            if isinstance(proj_deps, list):
                for r in proj_deps:
                    if isinstance(r, str) and r.strip():
                        packages.add(r.strip())

            # [project.optional-dependencies]
            opt = data.get("project", {}).get("optional-dependencies", {})
            for k, reqs in opt.items():
                if isinstance(reqs, list):
                    for r in reqs:
                        if isinstance(r, str) and r.strip():
                            packages.add(r.strip())

            # [dependency-groups] (PEP 735)
            groups = data.get("dependency-groups", {})
            for k, reqs in groups.items():
                if isinstance(reqs, list):
                    for r in reqs:
                        if isinstance(r, str) and r.strip():
                            packages.add(r.strip())

            # Poetry dependencies
            poetry = data.get("tool", {}).get("poetry", {})
            for dep_table in [
                poetry.get("dependencies", {}),
                poetry.get("dev-dependencies", {}),
            ]:
                if isinstance(dep_table, dict):
                    for pkg, spec in dep_table.items():
                        if isinstance(pkg, str) and pkg.lower() != "python":
                            packages.add(pkg.strip())
            for group_val in poetry.get("group", {}).values():
                if isinstance(group_val, dict):
                    for pkg in group_val.get("dependencies", {}).keys():
                        if isinstance(pkg, str) and pkg.lower() != "python":
                            packages.add(pkg.strip())

            # Flit metadata
            flit_meta = data.get("tool", {}).get("flit", {}).get("metadata", {})
            for r in flit_meta.get("requires", []):
                if isinstance(r, str) and r.strip():
                    packages.add(r.strip())
            for extra_reqs in flit_meta.get("requires-extra", {}).values():
                if isinstance(extra_reqs, list):
                    for r in extra_reqs:
                        if isinstance(r, str) and r.strip():
                            packages.add(r.strip())

            # PDM dev-dependencies
            pdm_dev = data.get("tool", {}).get("pdm", {}).get("dev-dependencies", {})
            if isinstance(pdm_dev, dict):
                for reqs in pdm_dev.values():
                    if isinstance(reqs, list):
                        for r in reqs:
                            if isinstance(r, str) and r.strip():
                                packages.add(r.strip())

            # Hatch extra-dependencies
            hatch_envs = data.get("tool", {}).get("hatch", {}).get("envs", {})
            for env_spec in hatch_envs.values():
                if isinstance(env_spec, dict):
                    for r in env_spec.get("extra-dependencies", []):
                        if isinstance(r, str) and r.strip():
                            packages.add(r.strip())
        except Exception as exc:
            logger.debug(f"Error parsing pyproject.toml in {worktree}: {exc}")

    # 2. setup.cfg discovery
    setup_cfg = worktree / "setup.cfg"
    if setup_cfg.is_file():
        try:
            cfg = configparser.ConfigParser()
            cfg.read_string(setup_cfg.read_text(encoding="utf-8", errors="replace"))
            if cfg.has_section("options.extras_require"):
                for _, v in cfg.items("options.extras_require"):
                    for line in v.splitlines():
                        line = line.strip()
                        if line and not line.startswith("#"):
                            packages.add(line)
            if cfg.has_section("options") and cfg.has_option("options", "install_requires"):
                for line in cfg.get("options", "install_requires").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        packages.add(line)
        except Exception as exc:
            logger.debug(f"Error parsing setup.cfg in {worktree}: {exc}")

    # 3. tox.ini discovery
    tox_ini = worktree / "tox.ini"
    if tox_ini.is_file():
        try:
            cfg = configparser.ConfigParser()
            cfg.read_string(tox_ini.read_text(encoding="utf-8", errors="replace"))
            for sec in cfg.sections():
                if "testenv" in sec and cfg.has_option(sec, "deps"):
                    for line in cfg.get(sec, "deps").splitlines():
                        line = line.strip()
                        if line and not line.startswith(("#", "-", "{", "[")):
                            # Filter out tox interpolation strings like {[testenv:x]deps}
                            packages.add(line)
        except Exception as exc:
            logger.debug(f"Error parsing tox.ini in {worktree}: {exc}")

    # 4. Requirements files discovery
    standard_req_files = [
        worktree / "requirements.txt",
        worktree / "requirements-dev.txt",
        worktree / "requirements_dev.txt",
        worktree / "dev-requirements.txt",
        worktree / "requirements-test.txt",
        worktree / "requirements_test.txt",
        worktree / "test-requirements.txt",
        worktree / "tox-requirements.txt",
    ]
    for rf in standard_req_files:
        if rf.is_file():
            req_files.append(rf)

    for sub in ["requirements", "tests/requirements"]:
        req_dir = worktree / sub
        if req_dir.is_dir():
            for rf in sorted(req_dir.glob("*.txt")):
                if rf.is_file() and rf not in req_files:
                    req_files.append(rf)

    # Sanitize package strings
    clean_packages: set[str] = set()
    for pkg in packages:
        pkg_clean = pkg.strip()
        if not pkg_clean or pkg_clean.startswith("#") or "{" in pkg_clean:
            continue
        clean_packages.add(pkg_clean)

    return sorted(clean_packages), req_files


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

    ensure_worktree_fixes(worktree)

    lockfile_hash = _compute_lockfile_hash(worktree)
    cache_key_raw = f"{repo}:{commit_sha}:{lockfile_hash}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8")).hexdigest()[:16]

    cache_root = Path.home() / ".jittest" / "envs" if cache_root is None else Path(cache_root)

    venv_dir = cache_root / f"env_{cache_key}"
    python_exe = get_venv_python(venv_dir)

    if python_exe.exists():
        try:
            _preflight_environment(python_exe, worktree)
            return {
                "venv_dir": str(venv_dir),
                "python_path": str(python_exe),
                "cached": True,
                "cache_key": cache_key,
                "lockfile_sha256": lockfile_hash,
            }
        except EnvSetupError:
            import shutil
            shutil.rmtree(venv_dir, ignore_errors=True)

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
    except subprocess.TimeoutExpired as exc:
        raise EnvSetupError(f"env_build_timeout: venv creation timed out at {venv_dir}: {exc}") from exc
    except Exception as exc:
        raise EnvSetupError(f"Failed to create venv at {venv_dir}: {exc}") from exc

    pip_exe = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("pip.exe" if sys.platform == "win32" else "pip")
    if not pip_exe.exists():
        raise EnvSetupError(f"pip executable not found in created venv: {pip_exe}")

    # 1. Install core test & build infrastructure into venv
    core_pkgs = ["pytest", "setuptools-scm", "wheel", "packaging", "pluggy", "iniconfig", "exceptiongroup"]
    try:
        res_pt = subprocess.run(
            [str(pip_exe), "install", *core_pkgs],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
        if res_pt.returncode != 0:
            err_tail = res_pt.stderr[-1000:] or res_pt.stdout[-1000:]
            raise EnvSetupError(f"pip install core test packages failed:\n{err_tail}")
    except subprocess.TimeoutExpired as exc:
        raise EnvSetupError(f"env_build_timeout: pip install core test packages timed out: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"pip install core packages exception: {exc}") from exc

    # 2. Discover package requirements and requirements.txt files first
    discovered_pkgs, req_files = _discover_extras_and_requirements(worktree)

    # 3. Install requirements files (under bounded timeouts)
    for rf in req_files:
        try:
            subprocess.run(
                [str(pip_exe), "install", "-r", str(rf)],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            raise EnvSetupError(f"env_build_timeout: pip install -r {rf.name} timed out after 60s: {exc}") from exc
        except Exception:
            pass

    # 4. Install discovered packages
    if discovered_pkgs:
        chunk_size = 15
        for i in range(0, len(discovered_pkgs), chunk_size):
            chunk = discovered_pkgs[i : i + chunk_size]
            try:
                subprocess.run(
                    [str(pip_exe), "install", *chunk],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=60,
                )
            except subprocess.TimeoutExpired as exc:
                raise EnvSetupError(f"env_build_timeout: pip install package chunk timed out after 60s: {exc}") from exc
            except Exception:
                pass

    # 5. Install project in editable mode (with real dependencies under bounded resolver timeout)
    has_pyproject = (worktree / "pyproject.toml").exists()
    has_setup = (worktree / "setup.py").exists() or (worktree / "setup.cfg").exists()

    if has_pyproject or has_setup:
        try:
            res_e = subprocess.run(
                [str(pip_exe), "install", "-e", str(worktree)],
                cwd=str(worktree),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=60,
            )
            if res_e.returncode != 0:
                # Fallback to --no-build-isolation -e
                subprocess.run(
                    [str(pip_exe), "install", "--no-build-isolation", "-e", str(worktree)],
                    cwd=str(worktree),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=60,
                )
        except subprocess.TimeoutExpired as exc:
            raise EnvSetupError(f"env_build_timeout: pip install -e {worktree} timed out after 60s: {exc}") from exc
        except Exception:
            pass

    # 6. Apply pytest monkeypatch backward-compatibility fix if needed
    try:
        sp_dirs = [
            venv_dir / "Lib" / "site-packages",
            venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages",
            venv_dir / "lib" / "site-packages",
        ]
        for sp in sp_dirs:
            if sp.exists():
                for mp_p in sp.glob("**/_pytest/monkeypatch.py"):
                    mp_text = mp_p.read_text(encoding="utf-8", errors="replace")
                    if "notset = NOTSET" not in mp_text and "from _pytest.compat import NOTSET" not in mp_text:
                        mp_p.write_text(mp_text + "\nfrom _pytest.compat import NOTSET\nnotset = NOTSET\n", encoding="utf-8")
    except Exception as exc:
        logger.debug(f"Error applying pytest monkeypatch fix in {venv_dir}: {exc}")

    # Preflight check after installation
    _preflight_environment(python_exe, worktree)

    return {
        "venv_dir": str(venv_dir),
        "python_path": str(python_exe),
        "cached": False,
        "cache_key": cache_key,
        "lockfile_sha256": lockfile_hash,
    }
