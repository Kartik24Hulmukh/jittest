"""Continuous-run memory soak harness: determinism, leak detection, honesty."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import soak_memory  # noqa: E402


class SoakMemoryTest(unittest.TestCase):
    def test_short_soak_is_deterministic_and_leak_free(self):
        report = soak_memory.soak(segments=6, ops=120)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["distinct_digests"], 1)
        self.assertTrue(report["deterministic"])
        self.assertEqual(report["total_ops"], 720)
        self.assertIsNotNone(report["latency_ms"]["p99"])

    def test_same_seed_reproduces_identical_digest(self):
        first = soak_memory.soak(segments=3, ops=80)
        second = soak_memory.soak(segments=3, ops=80)
        self.assertEqual(first["segment_digest"], second["segment_digest"])

    def test_slope_detects_a_synthetic_leak(self):
        # Detector sensitivity: a 10 KiB-per-1k-ops ramp must be caught.
        xs = [float(i) for i in range(1, 21)]
        ys = [1000.0 + 10.0 * x for x in xs]
        slope = soak_memory.least_squares_slope(xs, ys)
        self.assertAlmostEqual(slope, 10.0, places=6)
        self.assertGreater(slope, soak_memory.LEAK_SLOPE_LIMIT_KIB)

    def test_slope_is_zero_for_flat_and_degenerate_series(self):
        self.assertEqual(soak_memory.least_squares_slope([1.0, 2.0], [5.0, 5.0]), 0.0)
        self.assertEqual(soak_memory.least_squares_slope([3.0, 3.0], [1.0, 9.0]), 0.0)
        self.assertEqual(soak_memory.least_squares_slope([1.0], [1.0]), 0.0)

    def test_report_never_claims_container_or_ga_scope(self):
        report = soak_memory.soak(segments=3, ops=60)
        self.assertIn("not a container", report["scope_note"])
        self.assertNotIn("ga_ready", report)

    def test_cli_writes_json_evidence_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "evidence" / "soak.json"
            code = soak_memory.main(["--segments", "4", "--ops", "60",
                                     "--out", str(out)])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text())
            self.assertFalse(payload["leak_suspected"])
            self.assertEqual(payload["kind"], "continuous_run_memory_soak")


if __name__ == "__main__":
    unittest.main()
