"""Truth-boundary tests for the two evaluation harnesses.

Both harnesses can produce a number that looks like evidence and is not. These
tests pin the boundaries where that used to happen:

  * a headline catch rate whose denominator silently excluded failures, so one
    success beside four setup errors read as 100%
  * a zero-attempt run that still printed a rate instead of withholding it
  * a precision run whose false-positive rate survived mass measurement failure

Each assertion here corresponds to a number that would have been published.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bugs = load("eval_truth_bugs", "eval/run_bugsinpy.py")
fp = load("eval_truth_fp", "eval/false_positives.py")


class BugsInPyTruthTests(unittest.TestCase):
    def test_catch_status_uses_mechanical_oracle_not_assessor(self):
        self.assertEqual(bugs.classify(2, 1), "caught")
        self.assertEqual(bugs.classify(2, 0), "missed")

    def test_unmeasured_bug_is_never_a_miss(self):
        self.assertEqual(bugs.classify(0, 0), "not_measured")

    def test_headline_denominator_includes_errors(self):
        rows = [bugs.BugResult("p", "1", status="caught",
                               catching_candidates=1, model_requests=2)]
        rows += [bugs.BugResult("p", str(i), status="error") for i in range(2, 6)]
        summary = bugs.summarize(rows)
        self.assertEqual(summary["catch_rate"], 0.2)
        self.assertEqual(summary["conditional_catch_rate"], 1.0)
        self.assertEqual(summary["completion_rate"], 0.2)

    def test_skips_and_unmeasured_are_counted_separately(self):
        rows = [
            bugs.BugResult("p", "1", status="caught",
                           catching_candidates=1, model_requests=3),
            bugs.BugResult("p", "2", status="missed", model_requests=3),
            bugs.BugResult("p", "3", status="not_measured"),
            bugs.BugResult("p", "4", status="skipped"),
            bugs.BugResult("p", "5", status="error"),
        ]
        summary = bugs.summarize(rows)
        self.assertEqual(summary["bugs_attempted"], 5)
        self.assertEqual(summary["bugs_measured"], 2)
        self.assertEqual(summary["bugs_not_measured"], 1)
        self.assertEqual(summary["bugs_skipped"], 1)
        self.assertEqual(summary["bugs_errored"], 1)
        self.assertEqual(summary["model_requests_total"], 6)
        self.assertEqual(summary["catch_rate"], 0.2)

    def test_zero_attempts_is_not_zero_percent(self):
        summary = bugs.summarize([])
        self.assertIsNone(summary["catch_rate"])
        self.assertIsNone(summary["completion_rate"])
        self.assertIsNone(summary["conditional_catch_rate"])

    def test_unpriced_row_makes_the_run_unpriced(self):
        rows = [
            bugs.BugResult("p", "1", status="missed", model_requests=2,
                           priced=True, cost_usd=0.01),
            bugs.BugResult("p", "2", status="missed", model_requests=2,
                           priced=False),
        ]
        self.assertFalse(bugs.summarize(rows)["priced"])


class FalsePositiveTruthTests(unittest.TestCase):
    def test_zero_work_withholds_rate(self):
        summary = fp.summarize_rows([], 0)
        self.assertIsNone(summary["false_positive_rate"])
        self.assertFalse(summary["gate_ready"])

    def test_mass_failures_withhold_rate(self):
        rows = [{"reported": 0, "model_requests": 2}]
        rows += [{"error": "x", "model_requests": 0} for _ in range(9)]
        summary = fp.summarize_rows(rows, 10)
        self.assertIsNone(summary["false_positive_rate"])
        self.assertFalse(summary["gate_ready"])

    def test_sufficient_measurement_exposes_rate(self):
        rows = [{"reported": 1, "model_requests": 2}]
        rows += [{"reported": 0, "model_requests": 2} for _ in range(9)]
        summary = fp.summarize_rows(rows, 10)
        self.assertTrue(summary["gate_ready"])
        self.assertEqual(summary["false_positive_rate"], 0.1)
        self.assertEqual(summary["comments_per_100_prs"], 10.0)


if __name__ == "__main__":
    unittest.main()
