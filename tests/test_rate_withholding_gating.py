"""Tests for rate-withholding gating requirements in false_positives evaluation summary."""
from __future__ import annotations

import unittest

from eval.false_positives import summarize_rows


class RateWithholdingGatingTests(unittest.TestCase):
    def test_sub_floor_sample_with_80_percent_completion_withholds_rates(self):
        # 16 measured out of 20 attempted (80% completion), but measured (16) < MIN_ELIGIBLE_SAMPLE (20)
        rows = [{"model_requests": 1, "reported": 0} for _ in range(16)] + \
               [{"error": "setup failed", "model_requests": 0} for _ in range(4)]
        summary = summarize_rows(rows, 20, 0, window=("2.years", "90.days"))

        self.assertEqual(summary["prs_attempted"], 20)
        self.assertEqual(summary["prs_analysed"], 16)
        self.assertEqual(summary["completion_rate"], 0.80)
        self.assertTrue(summary["gate_ready"])
        self.assertFalse(summary["sample_floor_met"])
        self.assertFalse(summary["publishable"])

        self.assertIsNone(summary["false_positive_rate"])
        self.assertIsNone(summary["false_positive_rate_upper_bound_95"])
        self.assertIsNone(summary["comments_per_100_prs"])
        self.assertIsNone(summary["comments_per_100_prs_upper_bound_95"])

    def test_floor_met_and_80_percent_completion_emits_rates(self):
        # 20 measured out of 25 attempted (80% completion), measured (20) >= MIN_ELIGIBLE_SAMPLE (20)
        rows = [{"model_requests": 1, "reported": 0} for _ in range(20)] + \
               [{"error": "setup failed", "model_requests": 0} for _ in range(5)]
        summary = summarize_rows(rows, 25, 0, window=("2.years", "90.days"))

        self.assertEqual(summary["prs_attempted"], 25)
        self.assertEqual(summary["prs_analysed"], 20)
        self.assertEqual(summary["completion_rate"], 0.80)
        self.assertTrue(summary["gate_ready"])
        self.assertTrue(summary["sample_floor_met"])
        self.assertTrue(summary["publishable"])

        self.assertIsNotNone(summary["false_positive_rate"])
        self.assertIsNotNone(summary["false_positive_rate_upper_bound_95"])
        self.assertIsNotNone(summary["comments_per_100_prs"])
        self.assertIsNotNone(summary["comments_per_100_prs_upper_bound_95"])

    def test_completion_below_80_percent_withholds_rates(self):
        # 20 attempted, 15 measured (75% completion), measured (15) < MIN_ELIGIBLE_SAMPLE (20)
        rows = [{"model_requests": 1, "reported": 0} for _ in range(15)] + \
               [{"error": "setup failed", "model_requests": 0} for _ in range(5)]
        summary = summarize_rows(rows, 20, 0, window=("2.years", "90.days"))

        self.assertEqual(summary["prs_attempted"], 20)
        self.assertEqual(summary["prs_analysed"], 15)
        self.assertEqual(summary["completion_rate"], 0.75)
        self.assertFalse(summary["gate_ready"])
        self.assertFalse(summary["publishable"])

        self.assertIsNone(summary["false_positive_rate"])
        self.assertIsNone(summary["false_positive_rate_upper_bound_95"])
        self.assertIsNone(summary["comments_per_100_prs"])
        self.assertIsNone(summary["comments_per_100_prs_upper_bound_95"])


if __name__ == "__main__":
    unittest.main()
