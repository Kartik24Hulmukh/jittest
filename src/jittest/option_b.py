from __future__ import annotations

import subprocess
import tempfile
import sys
from pathlib import Path
from typing import Any
from .verify import RefusalReason, VerifyRefusalError

class OptionBRefusalError(VerifyRefusalError):
    def __init__(self, code: str, message: str, details: str = "", phase: str = "provision"):
        self.code = code
        self.details = details
        self.phase = phase
        super().__init__(
            RefusalReason(
                code=code,
                message=message,
                phase=phase,
                details=details,
            )
        )

def make_phase1_fetch_plan(requirements_file: str | Path, wheelhouse_dir: str | Path, backend: str = "docker") -> list[str]:
    # Phase 1: Networked Fetch Container
    # Input: Allowlisted package specifications from Discovery
    # Network: ENABLED
    # Execution: ZERO candidate code executed
    # Action: pip download --only-binary :all: --dest /wheelhouse
    return [
        backend, "run", "--rm",
        "-v", f"{Path(wheelhouse_dir).resolve()}:/wheelhouse",
        "--cap-drop", "ALL",
        "--user", "65534:65534",
        "--memory", "2g",
        "--cpus", "2",
        "python:3.12-slim",
        "python3", "-m", "pip", "download",
        "--only-binary", ":all:",
        "--dest", "/wheelhouse",
        "-r", str(requirements_file)
    ]

def make_phase2_install_plan(wheelhouse_dir: str | Path, worktree_dir: str | Path, backend: str = "docker") -> list[str]:
    # Phase 2: Isolated Test Container
    # Network: SEVERED (--network none)
    # Mounts: Wheelhouse (ro), Candidate Worktree (ro)
    # Action: pip install --no-index --find-links=/wheelhouse
    return [
        backend, "run", "--rm",
        "--network", "none",
        "-v", f"{Path(wheelhouse_dir).resolve()}:/wheelhouse:ro",
        "-v", f"{Path(worktree_dir).resolve()}:/workspace:ro",
        "--read-only",
        "python:3.12-slim",
        "sh", "-c",
        "python3 -m venv /tmp/venv && "
        "/tmp/venv/bin/pip install --no-index --find-links=/wheelhouse /workspace"
    ]

def run_option_b_provisioning(
    worktree_dir: Path,
    declared_dependencies: list[str],
    sbx_plan: Any,
) -> dict[str, Any]:
    backend = getattr(sbx_plan, "backend", "docker")
    if backend not in ("docker", "podman"):
        raise OptionBRefusalError(
            "unsupported_backend",
            f"Option B requires docker or podman backend, got: {backend}"
        )
    
    # We write dependencies to an ephemeral requirements file
    with tempfile.TemporaryDirectory() as tmpdir:
        req_file = Path(tmpdir) / "requirements.txt"
        req_file.write_text("\n".join(declared_dependencies) + "\n", encoding="utf-8")
        
        wheelhouse_dir = Path(tmpdir) / "wheelhouse"
        wheelhouse_dir.mkdir()
        
        # Build Phase 1 command
        cmd = make_phase1_fetch_plan(req_file, wheelhouse_dir, backend=backend)
        
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if res.returncode != 0:
                stderr = res.stderr or ""
                stdout = res.stdout or ""
                if "only-binary" in stderr or "only-binary" in stdout or "sdist" in stderr or "No matching distribution found" in stderr:
                    raise OptionBRefusalError(
                        "unsupported_packaging",
                        "dependency requires sdist compilation; only binary wheels allowed in Phase 1",
                        details=stderr
                    )
                elif "Could not find a version" in stderr or "network" in stderr or "Connection" in stderr:
                    raise OptionBRefusalError(
                        "fetch_network_error",
                        "upstream package index unreachable or timeout",
                        details=stderr
                    )
                else:
                    raise OptionBRefusalError(
                        "offline_install_failed",
                        "Phase 1 wheelhouse fetch failed",
                        details=stderr
                    )
        except subprocess.TimeoutExpired as exc:
            raise OptionBRefusalError(
                "timeout",
                "Phase 1 fetch phase exceeded 180s timeout",
                details=str(exc)
            )
        except FileNotFoundError:
            raise OptionBRefusalError(
                "unsupported_packaging",
                "docker or podman daemon is not available on host",
                details="executable not found"
            )
            
        return {
            "venv_dir": "",
            "python_path": "python",
            "cached": False,
            "cache_key": "",
            "lockfile_sha256": "",
            "exclude_newer_cutoff": "",
            "interpreter_version": "python",
            "resolved_versions": [],
            "provisioning": "option_b_two_phase",
            "wheelhouse_dir": str(wheelhouse_dir),
            "has_project_dependencies": True,
        }
