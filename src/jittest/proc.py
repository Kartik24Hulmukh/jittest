"""Bounded-memory subprocess capture with explicit resource ownership.

TemporaryFile owns capture handles across spawn errors, cancellation and normal
exit. Capture is bounded in memory. POSIX session cleanup also runs after parent
exit. On Windows every child is assigned to an OS job object created with
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; closing the job handle (owned by the same
ExitStack as the capture files) makes the kernel kill the whole member tree,
including descendants whose parent already exited. taskkill is only a fallback
when job creation/assignment fails. Recovery timestamps include decoding and file cleanup, not just process wait.
"""

from __future__ import annotations

import atexit
import contextlib
import math
import os
import subprocess

if os.name != "nt":
    import resource
import tempfile
import threading
import time
from threading import BoundedSemaphore
from typing import Any, BinaryIO

MAX_CAPTURE = 2 * 1024 * 1024
MAX_LIVE_PROCESSES = 4
_LIVE_PROCESSES = BoundedSemaphore(MAX_LIVE_PROCESSES)
_KILLERS: set[subprocess.Popen[Any]] = set()
_KILLERS_LOCK = threading.Lock()


def _reap_killers() -> None:
    """Discard completed helpers during operation, not only at interpreter exit."""
    with _KILLERS_LOCK:
        for process in tuple(_KILLERS):
            if process.poll() is not None:
                _KILLERS.discard(process)


atexit.register(_reap_killers)


def _create_kill_on_close_job(proc: subprocess.Popen[Any]) -> Any:
    """Assign a Windows child to a job whose close kills its descendants."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        return None
    # JOBOBJECT_EXTENDED_LIMIT_INFORMATION begins with IO counters and limits;
    # the BasicLimitInformation.LimitFlags field is at offset 48 on Windows.
    buf = ctypes.create_string_buffer(144)
    ctypes.c_uint32.from_buffer(buf, 48).value = 0x00002000  # KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(buf), ctypes.sizeof(buf)):
        kernel.CloseHandle(job)
        return None
    if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle)):
        kernel.CloseHandle(job)
        return None
    return job


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


def _limit_capture_size() -> None:
    if os.name != "nt":
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_CAPTURE, MAX_CAPTURE))



def _read_capture(stream: BinaryIO | None) -> str:
    if stream is None:
        return ""
    stream.seek(0)
    content = stream.read(MAX_CAPTURE).decode("utf-8", "replace")
    # Truncate the file to prevent disk exhaustion after reading cap
    stream.truncate(MAX_CAPTURE)
    return content


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
    Spawning is throttled to MAX_LIVE_PROCESSES concurrent processes to prevent
    OS-level scheduling starvation under load.
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
        if capture:
            popen_kwargs["preexec_fn"] = _limit_capture_size
        if capture:
            popen_kwargs["preexec_fn"] = _limit_capture_size

    t_start = time.perf_counter()
    timed_out = False

    # Acquire admission permit before entering the context (so we don't hold FD/child if we wait).
    _LIVE_PROCESSES.acquire()
    try:
        with contextlib.ExitStack() as resources:
            out_file = resources.enter_context(tempfile.TemporaryFile()) if capture else None
            err_file = resources.enter_context(tempfile.TemporaryFile()) if capture else None
            job = _create_kill_on_close_job()
            # Registered before spawn: on every exit path the kernel reclaims the tree.
            resources.callback(_close_job, job)
            
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                stdout=out_file if capture else subprocess.DEVNULL,
                stderr=err_file if capture else subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **popen_kwargs,
            )
<<<<<<< HEAD
            _assign_to_job(job, proc)
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
    finally:
        # Release the admission permit after the child and all resources are gone.
        _LIVE_PROCESSES.release()
