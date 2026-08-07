"""Container and namespace isolation for candidate execution."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "SandboxUnavailable", "SandboxPlan", "detect_backend", "probe_backend",
    "plan", "MODES", "DEFAULT_IMAGE",
]

MODES = ("auto", "required", "off")

# Pinned Python base image by immutable SHA-256 digest
DEFAULT_IMAGE = "python:3.13-slim@sha256:d8f76e73ec82d617937c8651c6c5ad37397b9195b00c5c363f886f4376c66cf1"

_MEMORY = "2g"
_PIDS = "256"

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_MOUNT = "/opt/jittest"


class SandboxUnavailable(RuntimeError):
    """No usable isolation backend, and the configuration requires one."""


@dataclass
class SandboxPlan:
    """How a candidate will actually be executed."""
    backend: str = "none"
    image: str = DEFAULT_IMAGE
    notes: list[str] = field(default_factory=list)

    @property
    def isolated(self) -> bool:
        return self.backend != "none"

    @property
    def network_denied(self) -> bool:
        """True only when egress is actually blocked by the backend."""
        return self.backend in ("docker", "podman", "bubblewrap")

    def as_dict(self) -> dict:
        return {
            "backend": self.backend,
            "image": self.image if self.backend in ("docker", "podman") else None,
            "isolated": self.isolated,
            "network_denied": self.network_denied,
            "notes": list(self.notes),
        }


def _usable(binary: str, args: list[str]) -> bool:
    if not shutil.which(binary):
        return False
    try:
        proc = subprocess.run(
            [binary, *args], capture_output=True, text=True,
            errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def detect_backend(preferred: str = "", *args, **kwargs) -> str:
    """Return the best available backend name, or ``"none"``."""
    candidates = ["podman", "docker", "bubblewrap"]

    if preferred:
        if preferred not in candidates:
            return "none"
        candidates = [preferred]

    for name in candidates:
        if name in ("podman", "docker") and _usable(name, ["info", "--format", "{{.ID}}"]):
            return name
        if name == "bubblewrap" and _usable("bwrap", ["--version"]):
            return "bubblewrap"
    return "none"


def _image_present(backend: str, image: str) -> bool:
    return _usable(backend, ["image", "inspect", image])


def probe_backend(backend: str, image: str = DEFAULT_IMAGE) -> tuple[bool, str]:
    if backend == "none":
        return True, ""
    argv = _probe_argv(backend, image)
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, errors="replace", timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, f"{backend} probe timed out"
    except OSError as exc:
        return False, f"{backend} probe could not start: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, f"{backend} probe exited {proc.returncode}: " + (
            detail[-1] if detail else "no output")
    if "jittest-sandbox-ok" not in proc.stdout:
        return False, f"{backend} probe produced no confirmation"
    return True, ""


def _probe_argv(backend: str, image: str) -> list[str]:
    marker = "print('jittest-sandbox-ok')"
    if backend in ("docker", "podman"):
        return [backend, "run", "--rm", "--network", "none", image,
                "python", "-c", marker]
    return ["bwrap", "--unshare-all", "--ro-bind", "/", "/", "--dev", "/dev",
            "--proc", "/proc", "--tmpfs", "/tmp", "--die-with-parent",
            _host_python(), "-c", marker]


def _host_python() -> str:
    import sys
    return sys.executable or "python3"


def plan(mode: str, preferred: str = "", image: str = DEFAULT_IMAGE,
         probe: bool = True) -> SandboxPlan:
    """Decide how candidates will run, once per pipeline run."""
    mode = (mode or "auto").strip().lower()
    if mode not in MODES:
        mode = "auto"

    if mode == "off":
        return SandboxPlan(backend="none", image=image, notes=[
            "sandbox disabled by configuration: candidate tests share the "
            "filesystem, network and user account of this runner. Do not use "
            "this setting on pull requests from outside collaborators."])

    backend = detect_backend(preferred)
    if mode == "required" and backend == "bubblewrap":
        backend = "none"

    if backend == "none":
        if mode == "required":
            raise SandboxUnavailable(
                "sandbox.mode is 'required' but no isolation backend is "
                "available. Install podman, docker or bubblewrap on this "
                "runner, or set sandbox.mode to 'auto' and accept that "
                "candidates run unconfined.")
        return SandboxPlan(backend="none", image=image, notes=[
            "no container or namespace backend found (looked for podman, "
            "docker, bubblewrap): candidates ran unconfined. Credentials were "
            "still withheld by the environment allowlist, but network egress "
            "and filesystem writes outside the checkout were not blocked."])

    if (mode == "auto" and backend in ("docker", "podman")
            and not _image_present(backend, image)):
        if detect_backend("bubblewrap") == "bubblewrap":
            backend = "bubblewrap"
        else:
            return SandboxPlan(backend="none", image=image, notes=[
                f"{backend} is available but the image {image!r} is not "
                f"present locally; candidates ran unconfined rather than "
                f"triggering an unannounced image pull mid-run. Run "
                f"'{backend} pull {image}' once, or set sandbox mode to "
                f"'required' to accept the pull."])

    if probe:
        ok, detail = probe_backend(backend, image)
        if not ok:
            if mode == "required":
                raise SandboxUnavailable(
                    f"sandbox.mode is 'required' and {backend} is installed but "
                    f"not working: {detail}")
            return SandboxPlan(backend="none", image=image, notes=[
                f"{backend} was found but did not work ({detail}); candidates "
                f"ran unconfined. This is reported rather than retried because "
                f"a sandbox that fails to start makes every candidate look "
                f"like a failing test, and a failing test on head is half of "
                f"a catch."])

    note = (f"candidates executed under {backend} with network egress denied"
            if backend != "bubblewrap" else
            "candidates executed under bubblewrap namespaces with network "
            "egress denied and host filesystem mounted read-only")
    return SandboxPlan(backend=backend, image=image, notes=[note])


def wrap(argv: list[str], workdir: Path | str, env: dict[str, str],
         sbx: SandboxPlan) -> tuple[list[str], dict[str, str]]:
    """Rewrite a candidate command so it runs inside the sandbox."""
    workdir = Path(workdir).resolve()
    if not sbx.isolated:
        return list(argv), dict(env)

    if sbx.backend in ("docker", "podman"):
        return _wrap_container(argv, workdir, env, sbx), {}
    return _wrap_bwrap(argv, workdir, env), dict(env)


def _container_paths(argv: list[str], workdir: Path) -> list[str]:
    prefix = str(workdir)
    out = []
    for token in argv:
        if token.startswith(prefix):
            tail = token[len(prefix):].replace(os.sep, "/").lstrip("/")
            out.append("/workspace/" + tail if tail else "/workspace")
        elif token.startswith("--junitxml=") and prefix in token:
            out.append("--junitxml=" + token.split("=", 1)[1].replace(
                prefix, "/workspace").replace(os.sep, "/"))
        else:
            out.append(token)
    return out


def _container_pythonpath(value: str, workdir: Path) -> list[str]:
    out: list[str] = []
    root = str(_PACKAGE_ROOT)
    for part in value.split(os.pathsep):
        if not part:
            continue
        if part.startswith(str(workdir)):
            tail = part[len(str(workdir)):].replace(os.sep, "/").lstrip("/")
            out.append("/workspace/" + tail if tail else "/workspace")
        elif part == root or part.startswith(root + os.sep):
            tail = part[len(root):].replace(os.sep, "/").lstrip("/")
            out.append(_PACKAGE_MOUNT + "/" + tail if tail else _PACKAGE_MOUNT)
    return out


def _wrap_container(argv: list[str], workdir: Path, env: dict[str, str],
                    sbx: SandboxPlan) -> list[str]:
    getuid_fn = getattr(os, "getuid", None)
    getgid_fn = getattr(os, "getgid", None)
    uid_gid = f"{getuid_fn()}:{getgid_fn()}" if getuid_fn and getgid_fn else "10001:10001"

    cmd = [
        sbx.backend, "run", "--rm",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--user", uid_gid,
        "--pids-limit", _PIDS,
        "--memory", _MEMORY,
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "-v", f"{workdir}:/workspace:rw",
        "-v", f"{_PACKAGE_ROOT}:{_PACKAGE_MOUNT}:ro",
        "-w", "/workspace",
    ]

    for name, value in sorted(env.items()):
        if name == "PATH":
            continue
        if name == "PYTHONPATH":
            value = ":".join(_container_pythonpath(value, workdir))
        cmd += ["-e", f"{name}={value}"]

    inner = _container_paths(argv, workdir)
    if inner and (inner[0].endswith("python") or "python" in Path(inner[0]).name):
        inner[0] = "python"
    return [*cmd, sbx.image, *inner]


def _wrap_bwrap(argv: list[str], workdir: Path, env: dict[str, str]) -> list[str]:
    return [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", str(workdir), str(workdir),
        "--chdir", str(workdir),
        *argv,
    ]
