"""Real process regressions: resource ownership, bounded retention, invalid input."""
import contextlib
import math
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from jittest.proc import MAX_CAPTURE, run_bounded


class ProcessLifecycleTests(unittest.TestCase):
    def test_capture_caps_both_streams_without_blocking_writer(self):
        result = run_bounded([sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(b'x'*(4*1024*1024)); "
            "sys.stderr.buffer.write(b'y'*(4*1024*1024))"], timeout=20)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "x" * MAX_CAPTURE)
        self.assertEqual(result.stderr, "y" * MAX_CAPTURE)

    def test_capture_disabled_has_no_readers_or_pipe_backpressure(self):
        before = threading.active_count()
        result = run_bounded([sys.executable, "-c",
            "import sys; sys.stdout.buffer.write(b'x'*(8*1024*1024)); "
            "sys.stderr.buffer.write(b'y'*(8*1024*1024))"], timeout=20, capture=False)
        self.assertEqual(result.returncode, 0)
        self.assertEqual((result.stdout, result.stderr), ("", ""))
        self.assertEqual(threading.active_count(), before)

    def test_failed_spawn_does_not_leave_named_capture_files(self):
        with tempfile.TemporaryDirectory() as directory:
            # A real child process owns this temp-directory setting, so parallel
            # test activity cannot contaminate or race the resource measurement.
            script = (
                "import tempfile, pathlib; from jittest.proc import run_bounded; "
                f"tempfile.tempdir={directory!r}\n"
                "try: run_bounded(['jittest-missing-executable-20260926'],timeout=1)\n"
                "except FileNotFoundError: pass\n"
                "assert not list(pathlib.Path(tempfile.tempdir).iterdir())\n"
            )
            result = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_nonfinite_timeouts_and_invalid_grace_are_rejected(self):
        for timeout in [math.nan, math.inf, -math.inf, 0, -1]:
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                run_bounded([sys.executable, "-c", "pass"], timeout=timeout)
        for grace in [math.nan, math.inf, -1]:
            with self.subTest(grace=grace), self.assertRaises(ValueError):
                run_bounded([sys.executable, "-c", "pass"], timeout=1, grace=grace)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process state inspection")
    def test_successful_parent_exit_stops_inherited_descendant(self):
        script = ("import subprocess,sys; "
                  "p=subprocess.Popen([sys.executable,'-c','import threading; threading.Event().wait(60)']); "
                  "print(p.pid,flush=True)")
        result = run_bounded([sys.executable, "-c", script], timeout=10)
        pid = int(result.stdout.strip())
        try:
            # Signal delivery is asynchronous; enforce the actual <200 ms
            # reclamation gate with a kernel death notification, never sleep.
            try:
                descriptor = os.pidfd_open(pid)
            except ProcessLookupError:
                descriptor = None
            if descriptor is not None:
                try:
                    self.assertTrue(select.select([descriptor], [], [], 0.199)[0])
                finally:
                    os.close(descriptor)
            try:
                state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0]
            except FileNotFoundError:
                state = "gone"
            self.assertIn(state, ("Z", "gone"), "descendant still executing after supervisor return")
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
