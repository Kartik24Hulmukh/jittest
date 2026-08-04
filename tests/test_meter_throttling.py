"""Tests for model request attempts, rate limiting classification, and throttle-aware ladder verdicts."""
from __future__ import annotations

import unittest

from eval.false_positives import classify_unmeasured, failure_reasons, summarize_rows
from eval.fp_ladder import INCONCLUSIVE_THROTTLED, ladder_verdict, verdict_note


class MeterThrottlingTests(unittest.TestCase):
    def test_rate_limited_row_classification(self):
        row = {
            "model_requests": 0,
            "model_request_attempts": 4,
            "rate_limited_candidates": 4,
            "targets_considered": 5,
            "candidates_generated": 0,
            "diff_status": "rate_limited",
        }
        self.assertEqual(classify_unmeasured(row), "rate_limited")

        reasons = failure_reasons([row])
        self.assertIn("rate_limited", reasons)
        self.assertNotIn("generation_made_no_request", reasons)

    def test_throttled_ladder_verdict(self):
        rungs = [
            {"risk_threshold": 0.35, "model_requests_total": 20, "rate_limited_candidates_total": 0},
            {
                "risk_threshold": 0.0,
                "model_requests_total": 0,
                "rate_limited_candidates_total": 50,
                "failure_reasons": {"rate_limited": 3},
            },
        ]
        self.assertEqual(ladder_verdict(rungs), INCONCLUSIVE_THROTTLED)
        self.assertTrue(verdict_note(INCONCLUSIVE_THROTTLED))

    def test_summary_includes_attempt_totals(self):
        rows = [
            {
                "model_requests": 2,
                "model_request_attempts": 4,
                "rate_limited_candidates": 1,
            },
            {
                "model_requests": 0,
                "model_request_attempts": 8,
                "rate_limited_candidates": 8,
                "diff_status": "rate_limited",
            },
        ]
        summary = summarize_rows(rows, len(rows))
        self.assertEqual(summary["model_request_attempts_total"], 12)
        self.assertEqual(summary["rate_limited_candidates_total"], 9)


if __name__ == "__main__":
    unittest.main()
