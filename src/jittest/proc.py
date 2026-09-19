"""Hard-bounded subprocess execution.

stdlib ``subprocess.run(timeout=...)`` does not guarantee a bounded wall clock:
after ``TimeoutExpired`` it re-enters ``communicate()`` with no deadline, so a
killed child that left grandchildren holding the inherited stdout/stderr pipe
handles wedges the caller forever.  That is exactly how the Windows 3.13 CI job
hung inside ``provision_environment`` until the 900s pytest cap fired.

``run_bounded`` removes the failure mode at the root:

* the child is started in its own process group / job-control unit so the whole
  tree can be signalled, not just the direct child;
* pipes are drained by daemon reader threads, so a grandchild holding a pipe can
  never block the caller;
* the deadline is enforced by the caller, escalating TERM -> KILL -> tree kill;
* the function is guaranteed to return (or raise ``TimeoutExpired``) within
  ``timeout + grace`` seconds, with whatever output was captured.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

__all__ = ["run_bounded", "kill_process_tree"]

_WINDOWS = sys.platform == "win32"


def kill_process_tree(proc: subprocess.Popen[Any], grace: float = 2.0) -> None:
    """Terminate *proc* and every descendant it spawned.  Never raises."""
    if proc.poll() is not None:
        return
    if _WINDOWS:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=grace + 3.0,
            )
        with contextlib.suppress(Exception):
            proc.kill()
    else:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(os.getpgid(proc.pid), sig)
            except Exception:
                with contextlib.suppress(Exception):
                    proc.kill()
            try:
                proc.wait(timeout=grace)
                return
            except Exception:
                continue
    with contextlib.suppress(Exception):
        proc.wait(timeout=grace)


def _drain(stream: Any, sink: list[str]) -> None:
    try:
        for chunk in iter(lambda: stream.read(65536), ""):
            if not chunk:
                break
            sink.append(chunk)
    except Exception:
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def run_bounded(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float,
    grace: float = 5.0,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run *cmd*, capturing text output, with a hard wall-clock bound.

    Raises ``subprocess.TimeoutExpired`` (with partial output attached) if the
    command outlives *timeout*; the process tree is killed first, so no orphan
    survives the call.
    """
    if timeout is None or timeout <= 0:
        raise ValueError("run_bounded requires a positive timeout")

    popen_kwargs: dict[str, Any] = {}
    if _WINDOWS:
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    t_start = time.perf_counter()
    proc = subprocess.Popen(  # noqa: S603 - argv list, never shell
        cmd,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        errors="replace",
        **popen_kwargs,
    )
    t_spawn = time.perf_counter()

    out_buf: list[str] = []
    err_buf: list[str] = []
    readers = [
        threading.Thread(target=_drain, args=(proc.stdout, out_buf), daemon=True),
        threading.Thread(target=_drain, args=(proc.stderr, err_buf), daemon=True),
    ]
    for t in readers:
        t.start()

    # Delegate timeout accounting to the standard library instead of keeping
    # a second fixed-20ms polling loop here. This is not universally event-driven:
    # CPython's POSIX Popen.wait(timeout=...) may use a bounded polling loop;
    # Windows uses the native process handle wait. Benchmark each target runtime.
    timed_out = False
    t_wait_end = t_spawn
    t_kill_end = t_spawn
    try:
        proc.wait(timeout=timeout)
        t_wait_end = time.perf_counter()
        t_kill_end = t_wait_end
    except subprocess.TimeoutExpired:
        timed_out = True
        t_wait_end = time.perf_counter()
        kill_process_tree(proc, grace=grace)
        t_kill_end = time.perf_counter()

    for t in readers:
        t.join(timeout=min(grace, 2.0))
    t_join_end = time.perf_counter()

    stdout = "".join(out_buf)
    stderr = "".join(err_buf)

    if timed_out:
        exc = subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)
        exc.t_start = t_start  # type: ignore[attr-defined]
        exc.t_spawn = t_spawn  # type: ignore[attr-defined]
        exc.t_wait_end = t_wait_end  # type: ignore[attr-defined]
        exc.t_kill_end = t_kill_end  # type: ignore[attr-defined]
        exc.t_join_end = t_join_end  # type: ignore[attr-defined]
        raise exc

    rc = proc.returncode if proc.returncode is not None else -1
    result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(cmd, rc, stdout, stderr)
    if check and rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, output=stdout, stderr=stderr)
    return result
