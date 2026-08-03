"""A zero-request row must name how far the funnel got.

Background. A cross-repo precision run reported ``dominant_failure:
no_model_requests`` on 29 of 32 requests PRs, while ``diff_status`` was ``ok``
on 30 of them. Within minutes that was written up as "target symbol ranking
filters out all changed functions" - a specific, testable, and unsupported
claim, because a row whose targets were all rejected by ranking carries
``below_risk_threshold`` or ``all_targets_ignored``, not ``ok``.

The artifact could not distinguish the two, so a reader supplied the
difference. These tests exist so that it never has to again: the bucket is
split by the funnel the pipeline already computes, and the residual case
carries an explicit statement that the cause is unknown.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.false_positives import (  # noqa: E402
    NO_CANDIDATES,
    NO_REQUESTS,
    NO_TARGETS,
    classify_unmeasured,
    describe,
    failure_reasons,
    summarize_rows,
)


def _measured(**extra) -> dict:
    row = {
        "base": "aaaaaaaa",
        "head": "bbbbbbbb",
        "reported": 0,
        "model_requests": 4,
        "diff_status": "ok",
        "targets_considered": 1,
        "candidates_generated": 4,
    }
    row.update(extra)
    return row


class TestClassification:
    def test_a_row_that_called_the_model_is_not_a_failure(self):
        assert classify_unmeasured(_measured()) is None

    def test_an_exception_is_keyed_by_type_name_only(self):
        row = {"error": "TimeoutError: read timed out after 300s on /v1/x"}
        assert classify_unmeasured(row) == "TimeoutError"

    def test_ranking_rejecting_every_symbol_is_its_own_bucket(self):
        row = _measured(
            model_requests=0, targets_considered=0, candidates_generated=0
        )
        assert classify_unmeasured(row) == NO_TARGETS

    def test_targets_that_generated_nothing_are_a_different_bucket(self):
        row = _measured(
            model_requests=0, targets_considered=3, candidates_generated=0
        )
        assert classify_unmeasured(row) == NO_CANDIDATES

    def test_a_row_without_funnel_counts_stays_undiagnosed(self):
        row = {"base": "aaaaaaaa", "head": "bbbbbbbb", "model_requests": 0}
        assert classify_unmeasured(row) == NO_REQUESTS

    def test_absent_is_not_the_same_as_zero(self):
        """None means unrecorded. Zero means ranking rejected everything."""
        absent = {"model_requests": 0, "targets_considered": None}
        zero = {"model_requests": 0, "targets_considered": 0}
        assert classify_unmeasured(absent) == NO_REQUESTS
        assert classify_unmeasured(zero) == NO_TARGETS

    def test_a_non_numeric_count_does_not_crash_the_summary(self):
        row = {"model_requests": 0, "targets_considered": "n/a"}
        assert classify_unmeasured(row) == NO_REQUESTS


class TestBucketing:
    def test_buckets_are_counted_and_ordered_by_size(self):
        rows = [
            _measured(model_requests=0, targets_considered=0),
            _measured(model_requests=0, targets_considered=0),
            _measured(
                model_requests=0, targets_considered=2, candidates_generated=0
            ),
        ]
        reasons = failure_reasons(rows)
        assert reasons == {NO_TARGETS: 2, NO_CANDIDATES: 1}
        assert next(iter(reasons)) == NO_TARGETS

    def test_measured_rows_are_not_bucketed(self):
        assert failure_reasons([_measured(), _measured()]) == {}


class TestDiagnosisGap:
    def test_an_undiagnosed_dominant_cause_says_so(self):
        rows = [{"model_requests": 0} for _ in range(3)]
        summary = summarize_rows(rows, 3)
        assert summary["dominant_failure"] == NO_REQUESTS
        assert summary["diagnosis_gap"]
        assert "cannot say" in summary["diagnosis_gap"]

    def test_a_diagnosed_dominant_cause_carries_no_gap(self):
        rows = [
            {"model_requests": 0, "targets_considered": 0} for _ in range(3)
        ]
        summary = summarize_rows(rows, 3)
        assert summary["dominant_failure"] == NO_TARGETS
        assert summary["diagnosis_gap"] is None

    def test_a_healthy_run_carries_no_gap(self):
        summary = summarize_rows([_measured() for _ in range(5)], 5)
        assert summary["dominant_failure"] is None
        assert summary["diagnosis_gap"] is None

    def test_the_sentence_warns_when_the_cause_is_only_a_symptom(self):
        summary = summarize_rows([{"model_requests": 0}], 1)
        sentence = describe(summary)
        assert "names where the pipeline stopped, not why" in sentence

    def test_the_sentence_does_not_warn_when_the_cause_is_real(self):
        summary = summarize_rows(
            [{"model_requests": 0, "targets_considered": 0}], 1
        )
        sentence = describe(summary)
        assert NO_TARGETS in sentence
        assert "not why" not in sentence


class TestGateIsUnaffected:
    def test_splitting_the_bucket_did_not_move_the_completion_floor(self):
        rows = [_measured() for _ in range(8)] + [{"model_requests": 0}] * 2
        summary = summarize_rows(rows, 10)
        assert summary["completion_rate"] == 0.8
        assert summary["gate_ready"] is True

    def test_a_collapsed_run_still_withholds_the_rate(self):
        rows = [_measured()] + [{"model_requests": 0}] * 9
        summary = summarize_rows(rows, 10)
        assert summary["gate_ready"] is False
        assert summary["false_positive_rate"] is None
