"""Container and namespace isolation for candidate execution.

This module closes the one item that has sat in "Still not fixed" in every
release notes section since 0.2.2:

    Candidates still share the filesystem, network, and user account with the
    runner. The environment allowlist withholds credentials; it is not a
    sandbox. Container/VM isolation remains the production-readiness blocker.

``execute._env_for`` withholds credentials by allowlist. That is a real defence
and it is not a boundary. A candidate test is model-written code chosen, in the
adversarial case, by whoever opened the pull request (premortem Defect 66: the
PR body reaches the generator prompt). Denylisting AST nodes in ``safety.py``
is, in that file's own words, a speed bump. The only version of this that holds
is to run the candidate somewhere it cannot reach the network, cannot write
outside the checkout, and cannot escalate.

Three backends, tried in this order:

``docker`` / ``podman``
    A container with ``--network none``, a read-only root filesystem, all
    capabilities dropped, ``no-new-privileges``, a pids limit, a memory limit,
    and exactly one writable bind: the checkout itself. Podman is preferred
    when both are present because rootless is the default there.

``bubblewrap``
    Unprivileged Linux namespaces. No daemon, no image pull, available on most
    CI images and in most hardened environments. Weaker than a container on
    filesystem confinement (the host root is bind-mounted read-only so the
    interpreter and its standard library remain reachable) and equally strong
    on the part that matters most, which is network egress.

``none``
    Direct execution, exactly as before this module existed.

The mode is chosen by configuration and the default is deliberately ``auto``:
isolate when a backend is available, fall back with a recorded warning when it
is not. ``required`` is the setting for running against untrusted pull requests
and it fails closed - if no backend is usable the run raises rather than
quietly degrading, because a sandbox that silently is not there is worse than
no sandbox at all. That is the same failure shape as Defect 22 (a failure to
measure reading as "nothing to do") and Defect 43 (an error and an empty result
sharing one return value), and it is the mistake this project keeps finding in
itself. It is not repeated here.

One rule governs every decision below: **isolation must never manufacture a
verdict.** A candidate that cannot start inside the sandbox is a NOTRUN, never
a FAIL. If the oracle's "fails on head" could be satisfied by the sandbox
refusing to launch the interpreter, then every sandbox misconfiguration would
read as a caught regression, and the product would be lying in the one direction
that matters. ``probe_backend`` exists to make that distinguishable before any
candidate runs.

Defects 72 and 73 below were both found by this repository's own CI, on the
only runners in the matrix that have a container engine installed. Seven jobs
were green because they never took the container path at all.
"""
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

# A stock slim image. Chosen because it is small, it is official, and it has no
# third-party packages in it - the candidate is supposed to import the repository
# under test and the standard library, and nothing else. Overridable, because a
# repository whose tests need compiled extensions will need its own image.
DEFAULT_IMAGE = "python:3.13-slim"

# Ceilings, not targets. A candidate that needs more than this is not a unit
# test; a candidate that tries to exceed it is trying to hurt the runner.
_MEMORY = "2g"
_PIDS = "256"

# Where jittest itself lives on the host. A candidate is executed by
# jittest._minirunner (or by the vendored pytest shim), so this directory is on
# the candidate's PYTHONPATH. Inside a container it is not, unless it is mounted
# - which is Defect 72, found by this project's own CI on the only runner in the
# matrix that has a container engine installed.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_PACKAGE_MOUNT = "/opt/jittest"


class SandboxUnavailable(RuntimeError):
    """No usable isolation backend, and the configuration requires one.

    Raised only in ``required`` mode. In ``auto`` mode the absence of a backend
    is a recorded warning, not an error.
    """


@dataclass
class SandboxPlan:
    """How a candidate will actually be executed.

    ``backend`` is what was selected. ``notes`` explains why, in a sentence fit
    to appear in a report - a user who believes their candidates are contained
    when they are not has been actively misled, so the fallback is always
    stated rather than merely implied by its absence.
    """
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
    """Is this binary present and does it actually answer?

    ``shutil.which`` is not enough. A Docker CLI with no reachable daemon is on
    PATH and exits non-zero on every command, which is exactly the shape that
    would turn "isolated" into "every candidate fails to start" - and therefore,
    without the NOTRUN rule in this module's docstring, into fabricated catches.
    """
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


def detect_backend(preferred: str = "") -> str:
    """Return the best available backend name, or ``"none"``.

    Podman before Docker: rootless is podman's default, so the same command
    yields a stronger result there. ``preferred`` pins one backend for testing
    and for users who have both and want the other.
    """
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
    """Is the image already in the local store? Never pulls."""
    return _usable(backend, ["image", "inspect", image])


def probe_backend(backend: str, image: str = DEFAULT_IMAGE) -> tuple[bool, str]:
    """Run a trivial command through the backend and confirm it succeeds.

    This is the guard against the failure mode named in the module docstring.
    Detection proves a binary answers; it does not prove a container can start,
    that the image is present, or that the kernel permits unprivileged user
    namespaces. Without this probe, all of those arrive later disguised as
    candidate failures, and a candidate failure on head is half of a catch.

    Returns ``(ok, detail)``. ``detail`` is empty on success.
    """
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
    """Decide how candidates will run, once per pipeline run.

    Called before any candidate executes so that a broken sandbox is a loud
    configuration error rather than a quiet run of NOTRUNs that the eval
    harness would later average into a catch rate.
    """
    mode = (mode or "auto").strip().lower()
    if mode not in MODES:
        mode = "auto"

    if mode == "off":
        return SandboxPlan(backend="none", image=image, notes=[
            "sandbox disabled by configuration: candidate tests share the "
            "filesystem, network and user account of this runner. Do not use "
            "this setting on pull requests from outside collaborators."])

    backend = detect_backend(preferred)
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

    # Defect 73. `docker run` pulls a missing image. In auto mode that turns
    # "isolate if you can" into an unannounced multi-hundred-megabyte download
    # in the middle of somebody's pull request, on a runner that may have no
    # registry access at all - and the failure would arrive disguised as
    # candidates that could not start. Auto isolates with what is already here;
    # `required` is where the user has asked for the image and a pull is the
    # expected cost of that request.
    if (mode == "auto" and backend in ("docker", "podman")
            and not _image_present(backend, image)):
        if detect_backend("bubblewrap") == "bubblewrap":
            # A namespace sandbox needs no image at all, so an absent image is
            # no reason to run unconfined when bwrap is right there.
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
            "egress denied and the host filesystem mounted read-only")
    return SandboxPlan(backend=backend, image=image, notes=[note])


def wrap(argv: list[str], workdir: Path | str, env: dict[str, str],
         sbx: SandboxPlan) -> tuple[list[str], dict[str, str]]:
    """Rewrite a candidate command so it runs inside the sandbox.

    Returns ``(argv, env)``. When the plan is unisolated both are returned
    unchanged, so the caller has exactly one code path.

    The container variants pass the environment through ``-e NAME=VALUE`` built
    from the allowlisted mapping the caller already computed. The allowlist is
    not re-derived here: two places deciding what a candidate may see is how
    one of them ends up wrong.
    """
    workdir = Path(workdir).resolve()
    if not sbx.isolated:
        return list(argv), dict(env)

    if sbx.backend in ("docker", "podman"):
        return _wrap_container(argv, workdir, env, sbx), {}
    return _wrap_bwrap(argv, workdir, env), dict(env)


def _container_paths(argv: list[str], workdir: Path) -> list[str]:
    """Rewrite host paths under the checkout to their in-container location.

    The candidate file and the junit report are addressed by absolute host
    path. Inside the container the checkout is bound at ``/workspace``, so an
    unrewritten path is simply absent and the run becomes a collection error -
    i.e. a NOTRUN dressed as a failure, which is the exact confusion this module
    is written to prevent.
    """
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
    """Translate a host PYTHONPATH into its in-container equivalent.

    Three cases, and the third is the one that matters. Paths under the
    checkout become paths under ``/workspace``. The jittest package root becomes
    the read-only mount. Anything else is a host path that simply does not exist
    in the image, and keeping it would leave a dead entry that silently changes
    what the candidate can import - so it is dropped rather than carried.
    """
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
    cmd = [
        sbx.backend, "run", "--rm",
        "--network", "none",             # the whole point
        "--read-only",                   # only the binds below are writable
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--pids-limit", _PIDS,
        "--memory", _MEMORY,
        "--tmpfs", "/tmp:rw,exec,nosuid,size=512m",
        "-v", f"{workdir}:/workspace:rw",
        # Read-only: the candidate must be able to import the runner, and must
        # not be able to edit the thing that is judging it.
        "-v", f"{_PACKAGE_ROOT}:{_PACKAGE_MOUNT}:ro",
        "-w", "/workspace",
    ]
    # Run as the invoking user so files the candidate writes into the bound
    # checkout do not end up owned by root, which would break reset_workdir
    # on the next candidate and leave the worktree undeletable.
    if hasattr(os, "getuid"):
        cmd += ["-u", f"{os.getuid()}:{os.getgid()}"]

    for name, value in sorted(env.items()):
        if name == "PATH":
            continue                     # the image's PATH, not the host's
        if name == "PYTHONPATH":
            value = ":".join(_container_pythonpath(value, workdir))
        cmd += ["-e", f"{name}={value}"]

    inner = _container_paths(argv, workdir)
    # The host interpreter path is meaningless inside the image.
    if inner and (inner[0].endswith("python") or "python" in Path(inner[0]).name):
        inner[0] = "python"
    return [*cmd, sbx.image, *inner]


def _wrap_bwrap(argv: list[str], workdir: Path, env: dict[str, str]) -> list[str]:
    """Namespace isolation with no daemon and no image.

    ``--unshare-all`` includes the network namespace, and no interface is
    configured inside it, so egress is denied. The host root is bound read-only
    because the candidate must still be able to execute the interpreter and
    import the standard library; the checkout is re-bound read-write on top,
    which is the only place a candidate is permitted to leave anything behind.
    """
    return [
        "bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",                 # no terminal-injection back at the host
        "--ro-bind", "/", "/",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--bind", str(workdir), str(workdir),
        "--chdir", str(workdir),
        *argv,
    ]
