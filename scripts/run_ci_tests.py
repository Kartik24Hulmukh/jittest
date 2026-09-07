import contextlib
import glob
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    test_files = sorted(glob.glob("tests/test_*.py"))
    log_path = "test_run.log"
    out_tmp_path = "test_output.tmp"

    def log(msg: str) -> None:
        print(msg, flush=True)
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
            fh.flush()

    # Clear previous logs
    for p in (log_path, out_tmp_path):
        if os.path.exists(p):
            with contextlib.suppress(OSError):
                os.remove(p)

    log(f"=== Running {len(test_files)} test files with pytest ===")

    failed = []
    timed_out = []
    suite_start = time.time()

    for i, f in enumerate(test_files, 1):
        if time.time() - suite_start > 900:
            log(f"\n[ABORT] Suite exceeded 900s budget. Last file: {f}")
            timed_out.append(f)
            break

        t0 = time.time()
        log(f"\n>>> [{i:02d}/{len(test_files):02d}] START {f}")

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "-v",
            "-s",
            "--durations=5",
            "--timeout=85",
            "--timeout-method=thread",
            f,
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = "src" + os.pathsep + env.get("PYTHONPATH", "")
        popen_kwargs: dict = {
            "stdin": subprocess.DEVNULL,
            "env": env,
        }
        if hasattr(os, "setsid"):
            popen_kwargs["start_new_session"] = True
        elif os.name == "nt":
            popen_kwargs["creationflags"] = getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )

        proc = None
        # Redirect stdout and stderr to a file so child processes never inherit
        # runner pipes or prevent step completion in CI runners.
        with open(out_tmp_path, "w", encoding="utf-8", errors="replace") as out_fh:
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=out_fh,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
                try:
                    proc.wait(timeout=100)
                except subprocess.TimeoutExpired:
                    elapsed = time.time() - t0
                    log(f">>> [{i:02d}/{len(test_files):02d}] TIMEOUT {f} exceeded 100s limit ({elapsed:.1f}s)!")
                    timed_out.append(f)
                    _kill_process_group(proc)
                else:
                    elapsed = time.time() - t0
                    if proc.returncode != 0:
                        log(f">>> [{i:02d}/{len(test_files):02d}] FAIL {f} (exit {proc.returncode}, {elapsed:.1f}s)")
                        failed.append((f, proc.returncode))
                    else:
                        log(f">>> [{i:02d}/{len(test_files):02d}] PASS {f} ({elapsed:.1f}s)")
            except Exception as exc:
                log(f">>> [{i:02d}/{len(test_files):02d}] ERROR {f}: {exc}")
                failed.append((f, -1))
                if proc:
                    _kill_process_group(proc)

        # After out_fh is closed, safely dump output tail if failed or timed out
        if (failed and failed[-1][0] == f) or (timed_out and timed_out[-1] == f):
            _dump_tail(out_tmp_path, log)

    with contextlib.suppress(OSError):
        if os.path.exists(out_tmp_path):
            os.remove(out_tmp_path)

    passed_count = len(test_files) - len(failed) - len(timed_out)
    log("\n=== Test Execution Summary ===")
    log(f"Total: {len(test_files)}, Passed: {passed_count}, Failed: {len(failed)}, Timed out: {len(timed_out)}")

    if failed or timed_out:
        if failed:
            log("\nFailed files:")
            for f, code in failed:
                log(f"  {f} (exit {code})")
        if timed_out:
            log("\nTimed out files:")
            for f in timed_out:
                log(f"  {f}")
        sys.exit(1)

    log("\nALL TEST FILES PASSED SUCCESSFULLY!")


def _dump_tail(file_path: str, log_fn) -> None:
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        tail = lines[-30:] if len(lines) > 30 else lines
        if tail:
            log_fn("--- Output tail ---")
            for line in tail:
                log_fn(f"  {line}")
            log_fn("-------------------")
    except Exception:
        pass


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Kill a process and all its descendants aggressively."""
    # First, collect all descendant PIDs (recursive) on Linux via /proc.
    descendants: list[int] = []
    if sys.platform == "linux":
        descendants = _get_all_descendants(proc.pid)

    # 1) Try SIGTERM on the process group for graceful shutdown.
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)

    # 2) SIGTERM each descendant individually (they may have different pgids).
    for pid in descendants:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)

    # Give processes a brief moment to exit cleanly.
    with contextlib.suppress(Exception):
        proc.wait(timeout=3)

    # 3) SIGKILL the process group.
    if hasattr(os, "killpg") and hasattr(os, "getpgid"):
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

    # 4) SIGKILL each descendant individually.
    for pid in descendants:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)

    # 5) Kill the main process directly.
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


def _get_all_descendants(pid: int) -> list[int]:
    """Recursively find all descendant PIDs via /proc on Linux."""
    descendants: list[int] = []
    try:
        children_path = Path(f"/proc/{pid}/task/{pid}/children")
        if children_path.exists():
            child_pids = children_path.read_text().split()
            for cpid_str in child_pids:
                cpid = int(cpid_str)
                descendants.append(cpid)
                descendants.extend(_get_all_descendants(cpid))
        else:
            # Fallback: scan /proc for processes whose ppid matches.
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    status = (entry / "status").read_text()
                    for line in status.splitlines():
                        if line.startswith("PPid:"):
                            ppid = int(line.split()[1])
                            if ppid == pid:
                                cpid = int(entry.name)
                                descendants.append(cpid)
                                descendants.extend(_get_all_descendants(cpid))
                            break
                except (OSError, ValueError):
                    continue
    except (OSError, ValueError):
        pass
    return descendants


if __name__ == "__main__":
    main()
