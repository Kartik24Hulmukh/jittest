"""Zero findings is not a zero percent false-positive rate.

The precision harness previously reported ``false_positive_rate: 0.0`` after a
run that surfaced no claims across 32 merged PRs. The arithmetic is right and
the conclusion is not: by the rule of three, the 95% upper bound on 0/32 is
9.4%, so that run is equally consistent with a tool that is wrong on one PR in
eleven.

This is the precision-side twin of the completion-rate floor in
``assert_measured.py``. That gate stops a run reporting a catch rate it did not
earn. These tests stop a run reporting a *precision* it did not earn, which is
the more seductive of the two because the misleading number looks like good
news.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from false_positives import (  # noqa: E402
    MIN_COMPLETION_RATE,
    describe,
    summarize_rows,
    upper_bound_95,
)


def _clean(count: int) -> list[dict]:
    """``count`` measured PRs that surfaced nothing."""
    return [
        {"base": f"aaaa{i:04d}", "head": f"bbbb{i:04d}",
         "reported": 0, "model_requests": 7}
        for i in range(count)
    ]


class RuleOfThree(unittest.TestCase):
    def test_zero_over_thirty_two_is_not_zero(self) -> None:
        self.assertAlmostEqual(upper_bound_95(0, 32), 0.094, places=3)

    def test_the_bound_shrinks_as_the_sample_grows(self) -> None:
        self.assertGreater(upper_bound_95(0, 10), upper_bound_95(0, 100))

    def test_an_empty_sample_has_no_bound_at_all(self) -> None:
        self.assertIsNone(upper_bound_95(0, 0))
        self.assertIsNone(upper_bound_95(0, -1))

    def test_a_tiny_sample_cannot_bound_below_one(self) -> None:
        # 3/2 exceeds 1.0 and must be clamped rather than printed as 150%.
        self.assertEqual(upper_bound_95(0, 2), 1.0)

    def test_a_nonzero_count_uses_wilson_and_exceeds_the_estimate(self) -> None:
        bound = upper_bound_95(1, 20)
        self.assertIsNotNone(bound)
        self.assertGreater(bound, 1 / 20)
        self.assertLessEqual(bound, 1.0)

    def test_every_observation_positive_still_bounds_at_one(self) -> None:
        self.assertEqual(upper_bound_95(10, 10), 1.0)


class SummaryReporting(unittest.TestCase):
    def test_a_clean_run_reports_both_the_rate_and_the_bound(self) -> None:
        summary = summarize_rows(_clean(32) + [{"error": "boom"}] * 8, 40)
        self.assertTrue(summary["gate_ready"])
        self.assertEqual(summary["false_positive_rate"], 0.0)
        self.assertAlmostEqual(
            summary["false_positive_rate_upper_bound_95"], 0.094, places=3
        )
        self.assertAlmostEqual(
            summary["comments_per_100_prs_upper_bound_95"], 9.4, places=1
        )

    def test_the_bound_is_never_present_without_the_rate(self) -> None:
        # Below the completion floor: both must be withheld together, so that
        # no caller can quote a bound as though the run were publishable.
        summary = summarize_rows(_clean(3) + [{"error": "boom"}] * 37, 40)
        self.assertFalse(summary["gate_ready"])
        self.assertIsNone(summary["false_positive_rate"])
        self.assertIsNone(summary["false_positive_rate_upper_bound_95"])

    def test_rows_without_a_model_request_are_not_evidence(self) -> None:
        rows = [{"reported": 0, "model_requests": 0} for _ in range(40)]
        summary = summarize_rows(rows, 40)
        self.assertEqual(summary["prs_analysed"], 0)
        self.assertFalse(summary["gate_ready"])
        self.assertIsNone(summary["false_positive_rate"])

    def test_model_requests_total_is_reported(self) -> None:
        summary = summarize_rows(_clean(32), 32)
        self.assertEqual(summary["model_requests_total"], 32 * 7)

    def test_the_completion_floor_is_still_eighty_percent(self) -> None:
        self.assertEqual(MIN_COMPLETION_RATE, 0.80)
        self.assertTrue(summarize_rows(_clean(8), 10)["gate_ready"])
        self.assertFalse(summarize_rows(_clean(7), 10)["gate_ready"])


class CopyablePhrasing(unittest.TestCase):
    def test_zero_findings_never_renders_as_a_zero_rate(self) -> None:
        sentence = describe(summarize_rows(_clean(32), 32))
        self.assertIn("9.4%", sentence)
        self.assertIn("does not establish that the rate is zero", sentence)
        self.assertNotIn("0.0% false", sentence)

    def test_a_finding_is_described_as_needing_adjudication(self) -> None:
        rows = _clean(31) + [{"reported": 1, "model_requests": 7}]
        sentence = describe(summarize_rows(rows, 32))
        self.assertIn("adjudication", sentence)

    def test_an_ungated_run_refuses_to_describe_a_rate(self) -> None:
        sentence = describe(summarize_rows(_clean(1), 40))
        self.assertIn("No false-positive rate", sentence)


if __name__ == "__main__":
    unittest.main()
