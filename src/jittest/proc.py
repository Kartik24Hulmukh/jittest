"""Bounded-memory subprocess capture with explicit resource ownership.

TemporaryFile owns capture handles across spawn errors, cancellation and normal
exit. Capture is bounded in memory, NOT on disk: hostile output still requires
an external filesystem quota. POSIX session cleanup also runs after parent exit.
Windows taskkill cannot contain descendants after their parent has exited; that
platform still needs OS-owned job containment before the launch gate can pass.
Recovery timestamps include decoding and file cleanup, not just process wait.
"""

from __future__ import annotations

import atexit
import contextlib
import math
import os
import subprocess
import tempfile
import threading
import time
from typing import Any, BinaryIO

MAX_CAPTURE = 2 * 1024 * 1024
_KILLERS: set[subprocess.Popen[Any]] = set()
_KILLERS_LOCK = threading.Lock()


def _reap_killers() -> None:
    """Discard completed helpers during operation, not only at interpreter exit."""
    with _KILLERS_LOCK:
        for process in tuple(_KILLERS):
            if process.poll() is not None:
                _KILLERS.discard(process)


atexit.register(_reap_killers)


def kill_process_tree(proc: subprocess.Popen[Any], grace: float = 1.0) -> None:
    """Signal the owned POSIX session even when its leader has already exited.

    Windows taskkill is a best-effort fallback, not lifetime containment. The
    bounded wait is not a guarantee about scheduling on an overloaded host.
    """
    _reap_killers()
    if os.name == "nt":
        if proc.poll() is None:
            try:
                helper = subprocess.Popen(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                with _KILLERS_LOCK:
                    _KILLERS.add(helper)
            except OSError:
                with contextlib.suppress(OSError):
                    proc.kill()
    else:
        try:
            os.killpg(proc.pid, 9)
        except (ProcessLookupError, PermissionError):
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=min(grace, 0.12))
    _reap_killers()


def _read_capture(stream: BinaryIO | None) -> str:
    if stream is None:
        return ""
    stream.seek(0)
    return stream.read(MAX_CAPTURE).decode("utf-8", "replace")


def run_bounded(
    cmd: list[str],
    *,
    timeout: float,
    cwd: str | os.PathLike[str] | None = None,
    env: dict[str, str] | None = None,
    check: bool = False,
    grace: float = 1.0,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute argv; cap retained output to MAX_CAPTURE bytes per stream.

    capture=False discards output without pipes or reader threads. Timeout and
    grace must be finite, with timeout positive and grace nonnegative. Child
    startup is recorded separately; timeout begins after Popen returns.
    """
    if timeout is None or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("run_bounded requires a finite positive timeout")
    if not math.isfinite(grace) or grace < 0:
        raise ValueError("run_bounded requires a finite nonnegative grace")
    popen_kwargs: dict[str, Any] = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    t_start = time.perf_counter()
    timed_out = False
    with contextlib.ExitStack() as resources:
        out_file = resources.enter_context(tempfile.TemporaryFile()) if capture else None
        err_file = resources.enter_context(tempfile.TemporaryFile()) if capture else None
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            stdout=out_file if capture else subprocess.DEVNULL,
            stderr=err_file if capture else subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **popen_kwargs,
        )
        t_spawn = time.perf_counter()
        try:
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            t_wait_end = time.perf_counter()
        finally:
            # Includes successful parent exits and BaseException cancellation.
            kill_process_tree(proc, grace=grace)
        t_kill_end = time.perf_counter()
        stdout = _read_capture(out_file)
        stderr = _read_capture(err_file)
    # Account for all capture, decoding and close/unlink work in recovery.
    t_join_end = time.perf_counter()
    if timed_out:
        exc = subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
        exc.t_start = t_start  # type: ignore[attr-defined]
        exc.t_spawn = t_spawn  # type: ignore[attr-defined]
        exc.t_wait_end = t_wait_end  # type: ignore[attr-defined]
        exc.t_kill_end = t_kill_end  # type: ignore[attr-defined]
        exc.t_join_end = t_join_end  # type: ignore[attr-defined]
        raise exc
    rc = proc.returncode if proc.returncode is not None else -1
    if check and rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(cmd, rc, stdout, stderr)
