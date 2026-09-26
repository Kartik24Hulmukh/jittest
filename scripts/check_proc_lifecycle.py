"""Independent Linux lifecycle gate; real descendants, no mocks or sleeps."""
import concurrent.futures
import contextlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from jittest.proc import MAX_CAPTURE, run_bounded


def live(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


def main():
    baseline_threads = threading.active_count()
    baseline_fds = len(os.listdir("/proc/self/fd"))
    baseline_files = set(Path(tempfile.gettempdir()).glob("jit-*.log"))
    parent_script = (
        "import subprocess,sys; "
        "p=subprocess.Popen([sys.executable,'-c','import threading; threading.Event().wait(60)']); "
        "print(p.pid,flush=True)"
    )
    def parent_exit(_):
        result = run_bounded([sys.executable, "-c", parent_script], timeout=10)
        return int(result.stdout.strip())
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
        pids = list(pool.map(parent_exit, range(100)))
    parent_seconds = time.perf_counter() - started
    survivors = [pid for pid in pids if live(pid)]
    # Harness owns cleanup, never confuse this with supervisor reclamation.
    for pid in survivors:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    def timeout(_):
        try:
            run_bounded([sys.executable, "-c", "import threading; threading.Event().wait(60)"], timeout=0.1)
        except subprocess.TimeoutExpired as exc:
            end = time.perf_counter()
            return {"instrumented_ms": (exc.t_join_end-exc.t_wait_end)*1000,
                    "actual_cleanup_ms": (end-exc.t_wait_end)*1000}
        raise AssertionError("expected timeout")
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
        durations = list(pool.map(timeout, range(100)))
    before_spawn_failure = set(Path(tempfile.gettempdir()).glob("jit-*.log"))
    with contextlib.suppress(FileNotFoundError):
        run_bounded(["jittest-nonexistent-executable-20260926"], timeout=1)
    failed_spawn_files = set(Path(tempfile.gettempdir()).glob("jit-*.log")) - before_spawn_failure
    cap = run_bounded([sys.executable, "-c", "import sys; sys.stdout.write('x'*(16*1024*1024))"], timeout=10)
    vals = sorted(d["actual_cleanup_ms"] for d in durations)
    report = {"workers":100,"parent_exit_journeys":100,"timeout_journeys":100,
              "surviving_descendants_before_harness_cleanup":len(survivors),
              "parent_exit_seconds":parent_seconds,"failed_spawn_tempfiles":len(failed_spawn_files),
              "owned_threads_delta":threading.active_count()-baseline_threads,
              "fd_delta":len(os.listdir("/proc/self/fd"))-baseline_fds,
              "capture_length":len(cap.stdout),"capture_cap":MAX_CAPTURE,
              "recovery_p50_p95_p99_max_ms":[vals[i] for i in [49,94,98,99]],
              "recovery_violations":sum(x>=200 for x in vals),"durations":durations}
    for file in set(Path(tempfile.gettempdir()).glob("jit-*.log"))-baseline_files:
        file.unlink(missing_ok=True)
    report["passed"] = (
        not survivors and not failed_spawn_files
        and report["owned_threads_delta"] == 0 and report["fd_delta"] == 0
        and report["capture_length"] == MAX_CAPTURE
        and report["recovery_violations"] == 0
    )
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
