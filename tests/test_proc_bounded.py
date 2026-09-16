"""Regression tests for jittest.proc.run_bounded (hard wall-clock bounds).

Root cause these lock down: the Windows/py3.13 CI hang where a killed installer
left a grandchild holding the inherited pipe and subprocess.run never returned.
"""

import subprocess
import sys
import time
import unittest

from jittest.proc import run_bounded


class TestRunBounded(unittest.TestCase):
    def test_normal_command_returns_captured_output(self):
        res = run_bounded([sys.executable, "-c", "print(\'hello\')"], timeout=30)
        self.assertEqual(res.returncode, 0)
        self.assertIn("hello", res.stdout)

    def test_nonzero_exit_is_reported_not_raised(self):
        res = run_bounded([sys.executable, "-c", "import sys; sys.stderr.write(\'boom\'); sys.exit(3)"], timeout=30)
        self.assertEqual(res.returncode, 3)
        self.assertIn("boom", res.stderr)

    def test_check_raises_called_process_error(self):
        with self.assertRaises(subprocess.CalledProcessError):
            run_bounded([sys.executable, "-c", "raise SystemExit(4)"], timeout=30, check=True)

    def test_sleeping_child_is_killed_within_bound(self):
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], timeout=1.0, grace=2.0)
        self.assertLess(time.monotonic() - start, 10.0)

    def test_grandchild_holding_pipe_cannot_wedge_caller(self):
        """The exact CI wedge: child spawns a long-lived grandchild that inherits
        stdout/stderr, then the child itself blocks.  run_bounded must still return."""
        script = (
            "import subprocess, sys, time\n"
            "subprocess.Popen([sys.executable, \'-c\', \'import time; time.sleep(120)\'])\n"
            "sys.stdout.write(\'spawned\\n\'); sys.stdout.flush()\n"
            "time.sleep(120)\n"
        )
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            run_bounded([sys.executable, "-c", script], timeout=2.0, grace=3.0)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 15.0, f"run_bounded wedged for {elapsed:.1f}s")
        self.assertIn("spawned", ctx.exception.output or "")

    def test_partial_output_is_attached_to_timeout(self):
        script = "import sys, time; sys.stdout.write(\'partial\\n\'); sys.stdout.flush(); time.sleep(60)"
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            run_bounded([sys.executable, "-c", script], timeout=1.5, grace=2.0)
        self.assertIn("partial", ctx.exception.output or "")

    def test_rejects_absent_timeout(self):
        with self.assertRaises(ValueError):
            run_bounded([sys.executable, "-c", "pass"], timeout=0)

    def test_repeated_timeouts_do_not_leak_threads(self):
        import threading

        before = threading.active_count()
        for _ in range(5):
            with self.assertRaises(subprocess.TimeoutExpired):
                run_bounded([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5, grace=1.0)
        time.sleep(0.5)
        self.assertLessEqual(threading.active_count() - before, 2)


if __name__ == "__main__":
    unittest.main()
