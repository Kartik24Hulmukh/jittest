"""A bucket name may not assert more than the funnel recorded.

Background. A precision run over 40 pallets/flask merges published this pair
of lines in one artifact:

    "model_requests_total": 0,
    "failure_reasons": {"targets_but_no_candidates": 25, ...}

The first says the model was never called. The second says targets reached
generation and generation declined. They cannot both be true, and the reader
of that artifact resolved the contradiction the way readers always do - by
believing the more specific-sounding of the two and reporting a diagnosis the
data did not support.

The contradiction was structural, not a fluke. ``classify_unmeasured`` returns
None for every row with ``model_requests > 0``, so the branch that produced
that bucket is only ever reached with zero requests. The name asserted the one
thing the funnel had already ruled out.

These tests pin both halves of the fix: the bucket now claims only that no
request was sent, and the branch that returns ``NO_PYTHON`` returns a defined
name instead of raising NameError.
"""
from __future__ import annotations

import unittest

from eval.false_positives import (
    NO_CANDIDATES,
    NO_PYTHON,
    NO_REQUESTS,
    NO_TARGETS,
    classify_unmeasured,
    describe,
    failure_reasons,
    summarize_rows,
)


def _row(**extra):
    row = {
        "base": "aaaaaaaa",
        "head": "bbbbbbbb",
        "reported": 0,
        "model_requests": 0,
        "diff_status": "ok",
    }
    row.update(extra)
    return row


class NoPythonBucketIsDefined(unittest.TestCase):
    """Defect 75. The name was used and never bound."""

    def test_the_constant_exists(self):
        self.assertIsInstance(NO_PYTHON, str)
        self.assertTrue(NO_PYTHON)

    def test_it_matches_the_diff_status_vocabulary(self):
        # The pipeline already emits this exact string as a diff_status. Two
        # spellings of one condition would split the histogram in half and
        # hide the dominant cause, which is the failure this module exists to
        # prevent.
        self.assertEqual(NO_PYTHON, "no_python_in_diff")

    def test_the_branch_returns_instead_of_raising(self):
        # Before the fix this raised NameError. ci.yml lints src and tests
        # only, so ruff F821 never read eval/, and no test reached the branch.
        row = _row(
            targets_considered=0,
            candidates_generated=0,
            python_files_changed=0,
        )
        self.assertEqual(classify_unmeasured(row), NO_PYTHON)

    def test_zero_targets_with_python_present_is_still_a_ranking_verdict(self):
        row = _row(
            targets_considered=0,
            candidates_generated=0,
            python_files_changed=3,
        )
        self.assertEqual(classify_unmeasured(row), NO_TARGETS)

    def test_a_summary_over_that_branch_does_not_crash(self):
        rows = [
            _row(
                targets_considered=0,
                candidates_generated=0,
                python_files_changed=0,
            )
            for _ in range(4)
        ]
        summary = summarize_rows(rows, 4)
        self.assertEqual(summary["dominant_failure"], NO_PYTHON)


class TheBucketClaimsOnlyWhatIsKnown(unittest.TestCase):
    """Defect 76. The old name contradicted model_requests_total."""

    def test_the_name_does_not_assert_generation_was_reached(self):
        self.assertEqual(NO_CANDIDATES, "generation_made_no_request")
        self.assertNotIn("candidates", NO_CANDIDATES)

    def test_targets_with_no_request_is_that_bucket(self):
        row = _row(targets_considered=3, candidates_generated=0)
        self.assertEqual(classify_unmeasured(row), NO_CANDIDATES)

    def test_the_branch_is_unreachable_with_a_request(self):
        # This is why the old name could never have been accurate: a row that
        # called the model is not a failure at all, so it never reaches the
        # candidates branch. Pinned so nobody restores the old name on the
        # theory that it described a real case.
        row = _row(
            model_requests=4, targets_considered=3, candidates_generated=0
        )
        self.assertIsNone(classify_unmeasured(row))

    def test_a_row_without_counts_is_still_undiagnosed(self):
        self.assertEqual(classify_unmeasured({"model_requests": 0}), NO_REQUESTS)


class TheContradictionIsAnnounced(unittest.TestCase):
    def test_the_dominant_bucket_carries_a_diagnosis_gap(self):
        rows = [
            _row(targets_considered=3, candidates_generated=0)
            for _ in range(25)
        ]
        summary = summarize_rows(rows, 40)
        self.assertEqual(summary["dominant_failure"], NO_CANDIDATES)
        gap = summary["diagnosis_gap"]
        self.assertTrue(gap)
        self.assertIn("contradiction", gap)
        self.assertIn("cannot say", gap)

    def test_the_gap_names_the_paths_worth_checking(self):
        rows = [_row(targets_considered=1, candidates_generated=0)]
        gap = summarize_rows(rows, 1)["diagnosis_gap"]
        for suspect in ("cache", "ceiling", "empty"):
            self.assertIn(suspect, gap)

    def test_the_published_sentence_warns_it_is_not_a_cause(self):
        rows = [_row(targets_considered=1, candidates_generated=0)]
        sentence = describe(summarize_rows(rows, 1))
        self.assertIn("names where the pipeline stopped, not why", sentence)

    def test_a_ranking_verdict_still_carries_no_gap(self):
        rows = [_row(targets_considered=0, python_files_changed=2)]
        summary = summarize_rows(rows, 1)
        self.assertEqual(summary["dominant_failure"], NO_TARGETS)
        self.assertIsNone(summary["diagnosis_gap"])


class TheFlaskRunIsReproduced(unittest.TestCase):
    """The exact histogram that exposed both defects."""

    def _rows(self):
        rows = []
        rows += [
            _row(targets_considered=3, candidates_generated=0)
            for _ in range(25)
        ]
        rows += [_row(diff_status="below_risk_threshold") for _ in range(8)]
        rows += [_row(diff_status="all_targets_ignored") for _ in range(5)]
        rows += [
            _row(targets_considered=0, python_files_changed=1)
            for _ in range(2)
        ]
        return rows

    def test_every_row_buckets_and_none_are_lost(self):
        rows = self._rows()
        self.assertEqual(len(rows), 40)
        reasons = failure_reasons(rows)
        self.assertEqual(sum(reasons.values()), 40)

    def test_the_dominant_cause_no_longer_contradicts_the_request_count(self):
        summary = summarize_rows(self._rows(), 40)
        self.assertEqual(summary["model_requests_total"], 0)
        self.assertEqual(summary["dominant_failure"], NO_CANDIDATES)
        self.assertEqual(summary["failure_reasons"][NO_CANDIDATES], 25)

    def test_the_rate_is_still_withheld(self):
        summary = summarize_rows(self._rows(), 40)
        self.assertEqual(summary["completion_rate"], 0.0)
        self.assertFalse(summary["gate_ready"])
        self.assertIsNone(summary["false_positive_rate"])


if __name__ == "__main__":
    unittest.main()
