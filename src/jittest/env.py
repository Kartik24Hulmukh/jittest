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


def get_commit_cutoff(repo_path: Path, commit_sha: str) -> str:
    """Extract ISO-8601 commit timestamp for uv --exclude-newer."""
    if not commit_sha:
        return ""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "show", "-s", "--date=format:%Y-%m-%dT%H:%M:%SZ", "--format=%cd", commit_sha],
            capture_output=True,
            text=True,
            errors="replace",
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return ""


def detect_python_requires(worktree: Path) -> str:
    """Detect python_requires from pyproject.toml, setup.cfg, or setup.py."""
    pyproject = worktree / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8", errors="replace"))
            req = data.get("project", {}).get("requires-python")
            if req:
                return str(req).strip()
        except Exception:
            pass

    setup_cfg = worktree / "setup.cfg"
    if setup_cfg.is_file():
        try:
            cfg = configparser.ConfigParser()
            cfg.read_string(setup_cfg.read_text(encoding="utf-8", errors="replace"))
            if cfg.has_section("options") and cfg.has_option("options", "python_requires"):
                return cfg.get("options", "python_requires").strip()
        except Exception:
            pass

    setup_py = worktree / "setup.py"
    if setup_py.is_file():
        try:
            content = setup_py.read_text(encoding="utf-8", errors="replace")
            m = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)['\"]", content)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    return ""


def resolve_target_python_version(python_requires: str) -> str:
    """Map python_requires constraint to a concrete Python version."""
    if not python_requires:
        return f"{sys.version_info.major}.{sys.version_info.minor}"

    if "<3.11" in python_requires or "<=3.10" in python_requires:
        return "3.10"
    if "<3.12" in python_requires or "<=3.11" in python_requires:
        return "3.11"
    if "<3.13" in python_requires or "<=3.12" in python_requires:
        return "3.12"

    if ">=3.12" in python_requires:
        return "3.12"
    if ">=3.11" in python_requires:
        return "3.11"
    if ">=3.10" in python_requires:
        return "3.10"
    if ">=3.9" in python_requires:
        return "3.9"
    if ">=3.8" in python_requires:
        return "3.10"

    return f"{sys.version_info.major}.{sys.version_info.minor}"


def find_uv() -> str | None:
    """Find uv executable on PATH or standard install locations."""
    import shutil
    uv_path = shutil.which("uv")
    if uv_path:
        return uv_path

    candidates = [
        Path.home() / ".local" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv"),
        Path.home() / ".cargo" / "bin" / ("uv.exe" if sys.platform == "win32" else "uv"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def provision_environment(
    worktree_dir: Path | str,
    commit_sha: str,
    repo_path: Path | str,
    cache_root: Path | str | None = None,
) -> dict[str, Any]:
    """Provision an isolated virtual environment for a worktree using uv era-correct resolution.

    Returns:
        {
            "venv_dir": str,
            "python_path": str,
            "cached": bool,
            "cache_key": str,
            "lockfile_sha256": str,
            "exclude_newer_cutoff": str,
            "interpreter_version": str,
            "resolved_versions": list[str],
        }

    Raises:
        EnvSetupError: If venv creation, pip install, or preflight check fails.
    """
    worktree = Path(worktree_dir).resolve()
    repo = Path(repo_path).resolve()

    ensure_worktree_fixes(worktree)

    cutoff = get_commit_cutoff(repo, commit_sha)
    py_req = detect_python_requires(worktree)
    target_py = resolve_target_python_version(py_req)
    uv_exe = find_uv()

    lockfile_hash = _compute_lockfile_hash(worktree)
    cache_key_raw = f"{repo}:{commit_sha}:{target_py}:{cutoff}:{lockfile_hash}"
    cache_key = hashlib.sha256(cache_key_raw.encode("utf-8")).hexdigest()[:16]

    cache_root = Path.home() / ".jittest" / "envs" if cache_root is None else Path(cache_root)

    venv_dir = cache_root / f"env_{cache_key}"
    python_exe = get_venv_python(venv_dir)

    if python_exe.exists():
        try:
            _preflight_environment(python_exe, worktree)
            resolved_versions: list[str] = []
            py_version_str = ""
            try:
                if uv_exe:
                    res_fr = subprocess.run([uv_exe, "pip", "freeze", "--python", str(python_exe)], capture_output=True, text=True, errors="replace", timeout=30)
                    resolved_versions = res_fr.stdout.splitlines()
                else:
                    pip_exe = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("pip.exe" if sys.platform == "win32" else "pip")
                    if pip_exe.exists():
                        res_fr = subprocess.run([str(pip_exe), "freeze"], capture_output=True, text=True, errors="replace", timeout=30)
                        resolved_versions = res_fr.stdout.splitlines()
                res_v = subprocess.run([str(python_exe), "-V"], capture_output=True, text=True, errors="replace", timeout=10)
                py_version_str = res_v.stdout.strip() or res_v.stderr.strip()
            except Exception:
                pass

            return {
                "venv_dir": str(venv_dir),
                "python_path": str(python_exe),
                "cached": True,
                "cache_key": cache_key,
                "lockfile_sha256": lockfile_hash,
                "exclude_newer_cutoff": cutoff,
                "interpreter_version": py_version_str,
                "resolved_versions": resolved_versions,
            }
        except EnvSetupError:
            import shutil
            shutil.rmtree(venv_dir, ignore_errors=True)

    venv_dir.parent.mkdir(parents=True, exist_ok=True)

    # Create virtualenv with uv (or fallback to python -m venv)
    venv_created = False
    if uv_exe:
        try:
            subprocess.run([uv_exe, "python", "install", target_py], capture_output=True, timeout=120)
        except Exception:
            pass

        try:
            res_uv_venv = subprocess.run(
                [uv_exe, "venv", "--python", target_py, str(venv_dir)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=120,
            )
            if res_uv_venv.returncode == 0:
                venv_created = True
        except subprocess.TimeoutExpired as exc:
            raise EnvSetupError(f"env_build_timeout: uv venv creation timed out at {venv_dir}: {exc}") from exc
        except Exception:
            pass

    if not venv_created:
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

    python_exe = get_venv_python(venv_dir)
    pip_exe = venv_dir / ("Scripts" if sys.platform == "win32" else "bin") / ("pip.exe" if sys.platform == "win32" else "pip")

    def run_installer(args_list: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
        if uv_exe:
            cmd = [uv_exe, "pip", "install", "--python", str(python_exe)]
            if cutoff:
                cmd.extend(["--exclude-newer", cutoff])
            cmd.extend(args_list)
        else:
            cmd = [str(pip_exe), "install"] + args_list
        return subprocess.run(cmd, cwd=str(worktree), capture_output=True, text=True, errors="replace", timeout=timeout)

    # 1. Discover requirements files and extras
    discovered_pkgs, req_files = _discover_extras_and_requirements(worktree)

    # 2. Install requirements files FIRST, unmodified
    for rf in req_files:
        try:
            res_rf = run_installer(["-r", str(rf)], timeout=90)
            if res_rf.returncode != 0:
                logger.debug(f"Installer -r {rf.name} failed: {res_rf.stderr[-500:]}")
        except subprocess.TimeoutExpired as exc:
            raise EnvSetupError(f"env_build_timeout: install -r {rf.name} timed out after 90s: {exc}") from exc
        except Exception:
            pass

    # 3. Install core test & build infrastructure
    core_pkgs = ["pytest", "setuptools-scm", "wheel", "packaging", "pluggy", "iniconfig", "exceptiongroup"]
    try:
        res_pt = run_installer(core_pkgs, timeout=90)
        if res_pt.returncode != 0 and not uv_exe:
            err_tail = res_pt.stderr[-1000:] or res_pt.stdout[-1000:]
            raise EnvSetupError(f"pip install core test packages failed:\n{err_tail}")
    except subprocess.TimeoutExpired as exc:
        raise EnvSetupError(f"env_build_timeout: install core test packages timed out: {exc}") from exc
    except Exception as exc:
        if isinstance(exc, EnvSetupError):
            raise
        raise EnvSetupError(f"install core packages exception: {exc}") from exc

    # 4. Install discovered package extras
    if discovered_pkgs:
        chunk_size = 15
        for i in range(0, len(discovered_pkgs), chunk_size):
            chunk = discovered_pkgs[i : i + chunk_size]
            try:
                run_installer(chunk, timeout=60)
            except subprocess.TimeoutExpired as exc:
                raise EnvSetupError(f"env_build_timeout: install package chunk timed out: {exc}") from exc
            except Exception:
                pass

    # 5. Install project in editable mode
    has_pyproject = (worktree / "pyproject.toml").exists()
    has_setup = (worktree / "setup.py").exists() or (worktree / "setup.cfg").exists()

    if has_pyproject or has_setup:
        try:
            res_e = run_installer(["-e", str(worktree)], timeout=60)
            if res_e.returncode != 0:
                run_installer(["--no-build-isolation", "-e", str(worktree)], timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise EnvSetupError(f"env_build_timeout: install -e {worktree} timed out: {exc}") from exc
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

    # 7. Capture resolved versions (freeze output) and interpreter version
    resolved_versions: list[str] = []
    py_version_str = ""
    try:
        if uv_exe:
            res_fr = subprocess.run([uv_exe, "pip", "freeze", "--python", str(python_exe)], capture_output=True, text=True, errors="replace", timeout=30)
            resolved_versions = res_fr.stdout.splitlines()
        else:
            if pip_exe.exists():
                res_fr = subprocess.run([str(pip_exe), "freeze"], capture_output=True, text=True, errors="replace", timeout=30)
                resolved_versions = res_fr.stdout.splitlines()
        res_v = subprocess.run([str(python_exe), "-V"], capture_output=True, text=True, errors="replace", timeout=10)
        py_version_str = res_v.stdout.strip() or res_v.stderr.strip()
    except Exception:
        pass

    return {
        "venv_dir": str(venv_dir),
        "python_path": str(python_exe),
        "cached": False,
        "cache_key": cache_key,
        "lockfile_sha256": lockfile_hash,
        "exclude_newer_cutoff": cutoff,
        "interpreter_version": py_version_str,
        "resolved_versions": resolved_versions,
    }
