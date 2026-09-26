"""Bounded subprocess capture with explicit process-tree ownership.

Pipe drainers retain at most MAX_CAPTURE bytes per stream, discarding excess
without writing capture files or limiting unrelated child filesystem writes.
Admission bounds both child count and reader count. Windows children start
suspended and cannot execute until assigned to a kill-on-close job.
"""

from __future__ import annotations

import atexit
import contextlib
import math
import os
import subprocess
import threading
import time
from threading import BoundedSemaphore
from typing import IO, Any

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


def _create_kill_on_close_job() -> Any | None:
    """Return a Windows job handle that kills its members on close, else None."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

    class _BasicLimit(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _ExtendedLimit(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimit),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _ExtendedLimit()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None
    return (kernel32, job)


def _assign_to_job(job: Any | None, proc: subprocess.Popen[Any]) -> bool:
    if job is None:
        return False
    kernel32, handle = job
    return bool(kernel32.AssignProcessToJobObject(handle, int(proc._handle)))  # type: ignore[attr-defined]


def _close_job(job: Any | None) -> None:
    if job is not None:
        kernel32, handle = job
        kernel32.CloseHandle(handle)


def _resume_contained(proc: subprocess.Popen[Any]) -> None:
    """Resume only after assignment; Popen has already closed its thread handle."""
    import ctypes
    from ctypes import wintypes

    ntdll = ctypes.WinDLL("ntdll")  # type: ignore[attr-defined]
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    ntdll.NtResumeProcess.restype = wintypes.LONG
    status = ntdll.NtResumeProcess(int(proc._handle))  # type: ignore[attr-defined]
    if status < 0:
        raise OSError(f"NtResumeProcess failed: {status:#x}")


class _Capture:
    """One owned drainer, bounded retained bytes, synchronous error propagation."""

    def __init__(self, stream: IO[bytes]) -> None:
        self.stream = stream
        self.content = bytearray()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._drain, name="jittest-capture")

    def _drain(self) -> None:
        try:
            while chunk := self.stream.read(65536):
                remaining = MAX_CAPTURE - len(self.content)
                if remaining > 0:
                    self.content.extend(chunk[:remaining])
        except BaseException as exc:
            self.error = exc

    def finish(self) -> None:
        self.thread.join()
        self.stream.close()

    def text(self) -> str:
        if self.error is not None:
            raise self.error
        return self.content.decode("utf-8", "replace")


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
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x00000004  # CREATE_SUSPENDED
    else:
        popen_kwargs["start_new_session"] = True

    t_start = time.perf_counter()
    timed_out = False

    # Acquire admission permit before entering the context (so we don't hold FD/child if we wait).
    _LIVE_PROCESSES.acquire()
    try:
        with contextlib.ExitStack() as resources:
            job = _create_kill_on_close_job()
            if os.name == "nt" and job is None:
                raise OSError("Cannot establish Windows job containment")
            owned_job = [job]
            resources.callback(lambda: _close_job(owned_job[0]))
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd) if cwd is not None else None,
                env=env,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **popen_kwargs,
            )
            readers: list[_Capture] = []
            try:
                if os.name == "nt":
                    if not _assign_to_job(job, proc):
                        raise OSError("Cannot assign child to Windows containment job")
                    _resume_contained(proc)
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        resources.callback(stream.close)
                        reader = _Capture(stream)
                        reader.thread.start()
                        readers.append(reader)
                t_spawn = time.perf_counter()
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                t_wait_end = time.perf_counter()
            finally:
                # Containment must close BEFORE joining drains: a descendant
                # can retain a pipe after its direct parent exits successfully.
                _close_job(owned_job[0])
                owned_job[0] = None
                kill_process_tree(proc, grace=grace)
                t_kill_end = time.perf_counter()
                for reader in readers:
                    reader.finish()
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None:
                        stream.close()
            stdout, stderr = (reader.text() for reader in readers) if capture else ("", "")
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
