"""Cross-platform admission and startup consume run_bounded's deadline."""
from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from jittest import proc


class _Gate:
    def __init__(self, result: bool, *, barrier: threading.Barrier | None = None,
                 on_acquire=None) -> None:
        self.result = result
        self.barrier = barrier
        self.on_acquire = on_acquire
        self.timeouts: list[float] = []
        self.releases = 0
        self.lock = threading.Lock()

    def acquire(self, *, timeout: float) -> bool:
        with self.lock:
            self.timeouts.append(timeout)
        if self.on_acquire:
            self.on_acquire()
        if self.barrier:
            self.barrier.wait(timeout=10)
        return self.result

    def release(self) -> None:
        with self.lock:
            self.releases += 1


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _Process:
    stdout = None
    stderr = None
    returncode = 0

    def __init__(self) -> None:
        self.wait_timeouts: list[float] = []

    def wait(self, *, timeout: float) -> int:
        self.wait_timeouts.append(timeout)
        return 0


class AdmissionDeadlineTests(unittest.TestCase):
    def test_failed_admission_never_starts_or_releases_child(self) -> None:
        gate = _Gate(False)
        with (
            patch.object(proc, "_LIVE_PROCESSES", gate),
            patch.object(subprocess, "Popen", side_effect=AssertionError("child started")),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            proc.run_bounded([sys.executable, "-c", "pass"], timeout=5)

        self.assertEqual(gate.timeouts, [5])
        self.assertEqual(gate.releases, 0)
        self.assertIsNone(caught.exception.t_spawn)
        self.assertTrue(caught.exception.admission_timeout)

    def test_hundred_simultaneous_waiters_refuse_without_spawn_or_release(self) -> None:
        gate = _Gate(False, barrier=threading.Barrier(100))

        def waiting_actor(_: int) -> bool:
            try:
                proc.run_bounded([sys.executable, "-c", "pass"], timeout=5)
            except subprocess.TimeoutExpired as exc:
                return bool(
                    getattr(exc, "admission_timeout", False)
                    and getattr(exc, "t_spawn", "not-set") is None
                )
            return False

        with (
            patch.object(proc, "_LIVE_PROCESSES", gate),
            patch.object(subprocess, "Popen", side_effect=AssertionError("child started")),
            ThreadPoolExecutor(max_workers=100) as pool,
        ):
            outcomes = list(pool.map(waiting_actor, range(100)))

        self.assertEqual(outcomes, [True] * 100)
        self.assertEqual(gate.timeouts, [5] * 100)
        self.assertEqual(gate.releases, 0)

    def test_admission_at_deadline_releases_exactly_once_without_spawn(self) -> None:
        clock = _Clock()
        gate = _Gate(True, on_acquire=lambda: setattr(clock, "now", 5.0))
        with (
            patch.object(proc, "_LIVE_PROCESSES", gate),
            patch.object(proc.time, "perf_counter", clock),
            patch.object(subprocess, "Popen", side_effect=AssertionError("child started")),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            proc.run_bounded([sys.executable, "-c", "pass"], timeout=5)

        self.assertEqual(gate.releases, 1)
        self.assertIsNone(caught.exception.t_spawn)
        self.assertTrue(caught.exception.admission_timeout)

    def test_admission_and_startup_are_deducted_from_process_wait(self) -> None:
        clock = _Clock()
        gate = _Gate(True, on_acquire=lambda: setattr(clock, "now", 4.0))
        child = _Process()
        job = object()

        def popen(*_args, **_kwargs):
            clock.now = 7.0
            return child

        with (
            patch.object(proc, "_LIVE_PROCESSES", gate),
            patch.object(proc.time, "perf_counter", clock),
            patch.object(proc, "_reaper_available", return_value=False),
            patch.object(proc, "_create_kill_on_close_job", return_value=job),
            patch.object(proc, "_assign_to_job", return_value=True),
            patch.object(proc, "_resume_contained"),
            patch.object(proc, "_close_job"),
            patch.object(proc, "kill_process_tree"),
            patch.object(subprocess, "Popen", side_effect=popen),
        ):
            result = proc.run_bounded(
                [sys.executable, "-c", "pass"], timeout=10, capture=False
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(child.wait_timeouts, [3.0])
        self.assertEqual(gate.releases, 1)

    def test_startup_exhausting_deadline_times_out_without_wait(self) -> None:
        clock = _Clock()
        gate = _Gate(True, on_acquire=lambda: setattr(clock, "now", 2.0))
        child = _Process()
        job = object()

        def popen(*_args, **_kwargs):
            clock.now = 5.0
            return child

        with (
            patch.object(proc, "_LIVE_PROCESSES", gate),
            patch.object(proc.time, "perf_counter", clock),
            patch.object(proc, "_reaper_available", return_value=False),
            patch.object(proc, "_create_kill_on_close_job", return_value=job),
            patch.object(proc, "_assign_to_job", return_value=True),
            patch.object(proc, "_resume_contained"),
            patch.object(proc, "_close_job"),
            patch.object(proc, "kill_process_tree"),
            patch.object(subprocess, "Popen", side_effect=popen),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            proc.run_bounded(
                [sys.executable, "-c", "pass"], timeout=5, capture=False
            )

        self.assertEqual(child.wait_timeouts, [])
        self.assertEqual(caught.exception.t_spawn, 5.0)
        self.assertEqual(gate.releases, 1)


if __name__ == "__main__":
    unittest.main()
