"""Run 9 regressions: readiness registry concurrency, barrier-driven chaos, recovery SLO.

Premortem #4 (readiness lifecycle drift): concurrent register/unregister/readyz must
never raise or corrupt the registry. Premortem #2/#3: fault injection must be driven by
load progress, not wall-clock sleeps, and recovery must be measured monotonically.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import pathlib
import threading
import unittest

from jittest.prod import probes

_SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "chaos_100x_probe.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("chaos_100x_probe", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class TestReadinessRegistryConcurrency(unittest.TestCase):
    def tearDown(self):
        for i in range(8):
            probes.unregister_readiness_check(f"churn_{i}")

    def test_concurrent_register_unregister_readyz_never_raises(self):
        errors: list[BaseException] = []
        start = threading.Barrier(24)

        def churn(i: int):
            start.wait()
            for _ in range(400):
                probes.register_readiness_check(f"churn_{i % 8}", lambda: None)
                probes.unregister_readiness_check(f"churn_{(i + 1) % 8}")

        def reader():
            start.wait()
            for _ in range(400):
                probes.readyz()

        def guarded(fn, *a):
            try:
                fn(*a)
            except BaseException as exc:  # noqa: BLE001 -- the point is to catch anything
                errors.append(exc)

        threads = [threading.Thread(target=guarded, args=(churn, i)) for i in range(16)]
        threads += [threading.Thread(target=guarded, args=(reader,)) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [])
        names = [name for name, _ in probes._READY_CHECKS]
        self.assertEqual(len(names), len(set(names)), "registry must hold unique names")

    def test_snapshot_is_immutable_and_includes_builtins(self):
        snap = probes.readiness_checks()
        self.assertIsInstance(snap, tuple)
        self.assertIn("core_imports", [n for n, _ in snap])

    def test_unregister_mutates_in_place(self):
        before = probes._READY_CHECKS
        probes.register_readiness_check("churn_0", lambda: None)
        probes.unregister_readiness_check("churn_0")
        self.assertIs(before, probes._READY_CHECKS)


class TestChaosHarnessPrimitives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = _load_harness()

    def test_scenario_matrix_has_120_distinct_records(self):
        matrix = self.h.scenario_matrix()
        keys = {(r["persona"], r["network"], r["headers"]) for r in matrix}
        self.assertEqual(len(matrix), 120)
        self.assertEqual(len(keys), 120)

    def test_progress_barrier_releases_on_count_and_on_finish(self):
        p = self.h.Progress()
        released = []
        t = threading.Thread(target=lambda: released.append(p.wait_for(3, timeout=5)))
        t.start()
        for _ in range(3):
            p.tick()
        t.join(timeout=5)
        self.assertEqual(released, [True])
        p2 = self.h.Progress()
        t2 = threading.Thread(target=lambda: released.append(p2.wait_for(10**9, timeout=5)))
        t2.start()
        p2.finish()
        t2.join(timeout=5)
        self.assertEqual(released, [True, True])

    def test_json_log_sink_validates_lines(self):
        sink = self.h.JsonLogSink()
        sink.write(json.dumps({"event": "ok"}) + "\n")
        sink.write("not json\n")
        sink.write(json.dumps({"event": "leak", "t": "ghp_abc"}) + "\n")
        self.assertEqual(sink.lines, 3)
        self.assertEqual(sink.bad, 1)
        self.assertEqual(sink.leaks, 1)

    def test_no_wall_clock_sleeps_in_fault_choreography(self):
        src = _SCRIPT.read_text(encoding="utf-8")
        chaos_body = src[src.index("def chaos():") : src.index("def slowloris")]
        loris_body = src[src.index("def slowloris") : src.index("t0 = time.perf_counter()")]
        self.assertNotIn("time.sleep", chaos_body)
        self.assertNotIn("time.sleep", loris_body)

    def test_small_run_measures_recovery_within_slo(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = self.h.main(["--clients", "20", "--requests", "600", "--seed", "7"])
        report = json.loads(out.getvalue())
        self.assertEqual(rc, 0, report)
        self.assertEqual(report["stderr_tracebacks"], 0)
        self.assertEqual(report["structured_logs"]["invalid_json"], 0)
        self.assertIsNotNone(report["recovery"]["recovery_ms"])
        self.assertLess(report["recovery"]["recovery_ms"], 200.0)
        self.assertEqual(report["distinct_client_scenarios"], 20)


if __name__ == "__main__":
    unittest.main()
