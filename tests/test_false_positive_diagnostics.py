"""A withheld rate that does not name its cause is a dead end.

The precision harness scored 32/40 on youtube-dl and 3/32 on psf/requests.
Both runs behaved correctly: the second withheld the rate and exited 1. But
the artifact could not say what happened to the 29 unmeasured PRs, so it was
impossible to tell whether jittest is fragile or whether requests is simply a
harder repository to check out and execute.

This is the third generation of one defect. The first reported a rate it had
not measured. The second reported a precision it had not earned. This one
reports a non-result it cannot explain. Each fix was correct and each left the
next version alive.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from false_positives import (  # noqa: E402
    NO_REQUESTS,
    describe,
    failure_reasons,
    summarize_rows,
)


def _clean(count: int) -> list[dict]:
    return [
        {"base": f"aaaa{i:04d}", "head": f"bbbb{i:04d}",
         "reported": 0, "model_requests": 7}
        for i in range(count)
    ]


def _failed(count: int, error: str) -> list[dict]:
    return [{"error": error, "model_requests": 0} for _ in range(count)]


class Bucketing(unittest.TestCase):
    def test_exceptions_are_keyed_by_type_not_by_message(self) -> None:
        rows = [
            {"error": "CalledProcessError: git checkout abc1234 failed"},
            {"error": "CalledProcessError: git checkout def5678 failed"},
        ]
        # Keying on the full string would make two buckets of one and hide the
        # fact that this is a single systematic failure.
        self.assertEqual(failure_reasons(rows), {"CalledProcessError": 2})

    def test_a_row_that_called_nothing_is_its_own_diagnosis(self) -> None:
        rows = [{"reported": 0, "model_requests": 0}]
        self.assertEqual(failure_reasons(rows), {NO_REQUESTS: 1})

    def test_measured_rows_are_not_failures(self) -> None:
        self.assertEqual(failure_reasons(_clean(5)), {})

    def test_buckets_are_ordered_most_common_first(self) -> None:
        rows = _failed(2, "TimeoutError: read") + _failed(9, "OSError: disk")
        self.assertEqual(list(failure_reasons(rows)), ["OSError", "TimeoutError"])

    def test_an_error_with_no_colon_still_buckets(self) -> None:
        self.assertEqual(failure_reasons([{"error": "boom"}]), {"boom": 1})


class SummaryNamesTheCause(unittest.TestCase):
    def test_a_collapsed_run_reports_its_dominant_failure(self) -> None:
        rows = _clean(3) + _failed(29, "CalledProcessError: git worktree")
        summary = summarize_rows(rows, 32)
        self.assertFalse(summary["gate_ready"])
        self.assertEqual(summary["dominant_failure"], "CalledProcessError")
        self.assertEqual(summary["failure_reasons"]["CalledProcessError"], 29)

    def test_a_healthy_run_has_no_dominant_failure(self) -> None:
        summary = summarize_rows(_clean(32), 32)
        self.assertTrue(summary["gate_ready"])
        self.assertIsNone(summary["dominant_failure"])
        self.assertEqual(summary["failure_reasons"], {})

    def test_the_cause_note_ships_with_every_summary(self) -> None:
        # Whoever reads the artifact without the code needs the warning that a
        # collapse may be a fact about the repository, not about jittest.
        self.assertIn("CAUSE_NOTE", summarize_rows(_clean(32), 32))


class CollapsePhrasing(unittest.TestCase):
    def test_the_withheld_sentence_names_the_cause(self) -> None:
        rows = _clean(3) + _failed(29, "CalledProcessError: git checkout")
        sentence = describe(summarize_rows(rows, 32))
        self.assertIn("No false-positive rate", sentence)
        self.assertIn("3/32", sentence)
        self.assertIn("CalledProcessError", sentence)
        self.assertIn("29 of 29 unmeasured", sentence)

    def test_a_collapse_never_renders_as_a_rate(self) -> None:
        rows = _clean(3) + _failed(29, "OSError: disk")
        sentence = describe(summarize_rows(rows, 32))
        self.assertNotIn("95% confidence", sentence)
        self.assertNotIn("0.0%", sentence)

    def test_a_gated_run_is_described_without_a_cause_clause(self) -> None:
        sentence = describe(summarize_rows(_clean(32), 32))
        self.assertNotIn("Dominant cause", sentence)


if __name__ == "__main__":
    unittest.main()
