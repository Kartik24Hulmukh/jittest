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
            except (FileNotFoundError, ProcessLookupError):
                state = "gone"
            self.assertIn(state, ("Z", "gone"), "descendant still executing after supervisor return")
        finally:
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


class StreamingCaptureTests(unittest.TestCase):
    def test_capture_uses_pipes_not_disk_and_preserves_large_child_files(self):
        # fstat inside the real child proves the live capture endpoint is a pipe,
        # not a tempfile truncated after exit. Child data files are unrestricted.
        with tempfile.TemporaryDirectory() as directory:
            result = run_bounded([sys.executable, "-c",
                "import os,stat,sys,pathlib; "
                "assert stat.S_ISFIFO(os.fstat(1).st_mode); "
                "assert stat.S_ISFIFO(os.fstat(2).st_mode); "
                "pathlib.Path('data').write_bytes(b'z'*(8*1024*1024)); "
                "sys.stdout.buffer.write(b'x'*(16*1024*1024)); "
                "sys.stderr.buffer.write(b'y'*(16*1024*1024))"],
                timeout=30, cwd=directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "x" * MAX_CAPTURE)
            self.assertEqual(result.stderr, "y" * MAX_CAPTURE)
            self.assertEqual((Path(directory) / "data").stat().st_size, 8*1024*1024)

    def test_timeout_joins_all_owned_capture_threads(self):
        before = {t.ident for t in threading.enumerate() if t.name == "jittest-capture"}
        with self.assertRaises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, "-c",
                "import sys,threading; sys.stdout.buffer.write(b'x'*(8*1024*1024)); "
                "sys.stdout.flush(); threading.Event().wait(60)"], timeout=1)
        self.assertEqual(before, {t.ident for t in threading.enumerate()
                                  if t.name == "jittest-capture"})

    @unittest.skipUnless(os.name == "nt", "Windows kernel containment")
    def test_windows_descendant_is_dead_on_success_and_timeout(self):
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        for hang in (False, True):
            with self.subTest(timeout=hang):
                script = (
                    "import subprocess,sys,threading; "
                    "p=subprocess.Popen([sys.executable,'-c',"
                    "'import threading; threading.Event().wait(60)']); "
                    "print(p.pid,flush=True); "
                    + ("threading.Event().wait(60)" if hang else "pass")
                )
                if hang:
                    with self.assertRaises(subprocess.TimeoutExpired) as caught:
                        run_bounded([sys.executable, "-c", script], timeout=2)
                    output = caught.exception.output
                else:
                    output = run_bounded([sys.executable, "-c", script], timeout=10).stdout
                pid = int(output.strip())
                handle = kernel32.OpenProcess(0x00100001, False, pid)
                if not handle:
                    # ERROR_INVALID_PARAMETER means the process is already gone.
                    self.assertEqual(ctypes.get_last_error(), 87)
                    continue
                try:
                    self.assertEqual(kernel32.WaitForSingleObject(handle, 199), 0,
                                     "descendant survived containment cleanup")
                finally:
                    kernel32.TerminateProcess(handle, 1)
                    kernel32.CloseHandle(handle)


@unittest.skipUnless(os.name == "posix", "POSIX session escape")
class EscapedPipeTests(unittest.TestCase):
    def test_escaped_writer_is_reported_without_stranding_reader_threads(self):
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / "escaped.pid"
            script = (
                "import subprocess,sys,pathlib; "
                "p=subprocess.Popen([sys.executable,'-c',"
                "'import threading;threading.Event().wait(60)'],start_new_session=True); "
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));print('done',flush=True)"
            )
            before = {t.ident for t in threading.enumerate() if t.name == "jittest-capture"}
            try:
                with self.assertRaisesRegex(RuntimeError, "capture pipe"):
                    run_bounded([sys.executable, "-c", script, str(pidfile)], timeout=2)
                self.assertEqual(before, {t.ident for t in threading.enumerate()
                                          if t.name == "jittest-capture"})
            finally:
                if pidfile.exists():
                    with contextlib.suppress(ProcessLookupError):
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
