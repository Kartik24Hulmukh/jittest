"""Continuous-run memory soak harness: determinism, leak detection, honesty."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_single_page_floor_step_is_not_a_leak(self):
        # Regression for the CI flake that blocked PR #209: one 4 KiB page
        # migration over 240 ops fits as ~33 KiB/1k-ops -- far above the
        # slope limit -- but the absolute retained growth is one page.
        xs = [0.12, 0.18, 0.24]
        ys = [65072.0, 65076.0, 65076.0]
        slope = soak_memory.least_squares_slope(xs, ys)
        self.assertGreater(slope, soak_memory.LEAK_SLOPE_LIMIT_KIB)
        growth = max(0.0, ys[-1] - min(ys))
        self.assertFalse(soak_memory.leak_verdict(
            slope, soak_memory.LEAK_SLOPE_LIMIT_KIB, growth,
            soak_memory.NOISE_ALLOWANCE_KIB))

    def test_real_leak_above_noise_allowance_is_still_flagged(self):
        # Sensitivity is preserved: at the committed 100k-op evidence scale a
        # true 1 KiB/1k-ops leak retains ~100 KiB >> the 16 KiB allowance.
        self.assertTrue(soak_memory.leak_verdict(
            slope=2.0, slope_limit=1.0, floor_growth=100.0,
            noise_allowance=soak_memory.NOISE_ALLOWANCE_KIB))

    def test_sub_limit_slope_is_never_a_leak_even_with_growth(self):
        self.assertFalse(soak_memory.leak_verdict(
            slope=0.5, slope_limit=1.0, floor_growth=1000.0,
            noise_allowance=soak_memory.NOISE_ALLOWANCE_KIB))

    def test_report_carries_growth_and_allowance_fields(self):
        report = soak_memory.soak(segments=3, ops=60)
        self.assertIn("floor_growth_kib", report)
        self.assertEqual(report["noise_allowance_kib"],
                         soak_memory.NOISE_ALLOWANCE_KIB)

    def test_cli_writes_json_evidence_and_exits_zero(self):
        # CLI serialization is not a live RSS stability test: a single 4 KiB
        # allocator page over 240 ops can exceed the production slope limit.
        # Keep the real pipeline, but give this unit test a controlled sensor.
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(soak_memory, "rss_kib", return_value=65072),
        ):
            out = Path(td) / "evidence" / "soak.json"
            code = soak_memory.main(["--segments", "4", "--ops", "60", "--out", str(out)])
            self.assertEqual(code, 0)
            payload = json.loads(out.read_text())
            self.assertFalse(payload["leak_suspected"])
            self.assertEqual(payload["kind"], "continuous_run_memory_soak")

    def test_cli_writes_failure_evidence_when_sensor_grows(self):
        # Exercise the real slope/CLI path; never relax the production threshold.
        with (
            tempfile.TemporaryDirectory() as td,
            patch.object(soak_memory, "rss_kib", side_effect=range(65072, 66072)),
        ):
            out = Path(td) / "leak.json"
            code = soak_memory.main(["--segments", "4", "--ops", "60", "--out", str(out)])
            self.assertEqual(code, 1)
            payload = json.loads(out.read_text())
            self.assertTrue(payload["leak_suspected"])
            self.assertGreater(
                payload["leak_slope_kib_per_1k_ops"], soak_memory.LEAK_SLOPE_LIMIT_KIB
            )


if __name__ == "__main__":
    unittest.main()
