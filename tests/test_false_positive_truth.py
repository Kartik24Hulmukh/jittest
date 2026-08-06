"""Regression tests for the false-positive measurement truth boundary."""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_harness():
    name = "false_positive_truth_harness"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "eval" / "false_positives.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FalsePositiveTruthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = load_harness()

    def test_zero_work_withholds_rate(self) -> None:
        summary = self.harness.summarize_rows([], 0)
        self.assertIsNone(summary["false_positive_rate"])
        self.assertIsNone(summary["completion_rate"])
        self.assertFalse(summary["gate_ready"])

    def test_mass_failures_withhold_rate(self) -> None:
        rows = [{"reported": 0, "model_requests": 2}]
        rows.extend(
            {"error": "setup failed", "model_requests": 0}
            for _ in range(9)
        )
        summary = self.harness.summarize_rows(rows, 10)
        self.assertEqual(summary["completion_rate"], 0.1)
        self.assertIsNone(summary["false_positive_rate"])
        self.assertFalse(summary["gate_ready"])

    def test_boundary_completion_exposes_rate(self) -> None:
        rows = [{"reported": 1, "model_requests": 2}]
        rows.extend(
            {"reported": 0, "model_requests": 2} for _ in range(19)
        )
        rows.extend(
            {"error": "setup failed", "model_requests": 0}
            for _ in range(5)
        )
        summary = self.harness.summarize_rows(rows, 25)
        self.assertEqual(summary["completion_rate"], 0.8)
        self.assertTrue(summary["gate_ready"])
        self.assertTrue(summary["sample_floor_met"])
        self.assertEqual(summary["false_positive_rate"], 0.05)
        self.assertEqual(summary["comments_per_100_prs"], 5.0)

    def test_below_boundary_withholds_rate(self) -> None:
        rows = [
            {"reported": 0, "model_requests": 1} for _ in range(79)
        ]
        rows.extend(
            {"error": "setup failed", "model_requests": 0}
            for _ in range(21)
        )
        summary = self.harness.summarize_rows(rows, 100)
        self.assertEqual(summary["completion_rate"], 0.79)
        self.assertIsNone(summary["false_positive_rate"])
        self.assertFalse(summary["gate_ready"])


if __name__ == "__main__":
    unittest.main()
