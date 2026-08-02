"""The selection window is part of the measurement, not part of the plumbing.

Every precision number this project publishes is conditional on which merges
were eligible to be looked at, and that was decided by two git arguments that
appeared in no output. Two separate investigations - a requests run that could
only find 6 eligible PRs against a floor of 20, and a six-repository survey
that found zero eligible pairs and blamed squash merges - traced back to the
same hardcoded pair.

The defaults do not move here. What changes is that they are recorded, and
that overriding them costs the caller a caveat attached to the sentence they
publish. These tests exist so that the cheap way to enlarge a sample stays
visible rather than becoming an unremarked edit to a constant.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.false_positives import (  # noqa: E402
    DEFAULT_SINCE,
    DEFAULT_UNTIL,
    MIN_ELIGIBLE_SAMPLE,
    describe,
    summarize_rows,
    window_is_default,
)


def _measured(**extra: object) -> dict:
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


def _publishable_rows(count: int = MIN_ELIGIBLE_SAMPLE) -> list[dict]:
    return [_measured() for _ in range(count)]


class TestTheDefaultIsTheMethod:
    """The settling time is a claim about evidence, so it is pinned."""

    def test_the_settling_time_is_ninety_days(self) -> None:
        # If this test fails because someone shortened the window to make a
        # sample bigger, that is the failure working. A merge that has not
        # had time to be reverted is not evidence of a clean merge.
        assert DEFAULT_UNTIL == "90.days"

    def test_the_lookback_is_two_years(self) -> None:
        assert DEFAULT_SINCE == "2.years"

    def test_the_defaults_are_recognised_as_default(self) -> None:
        assert window_is_default(DEFAULT_SINCE, DEFAULT_UNTIL) is True

    def test_a_narrowed_settling_time_is_not_default(self) -> None:
        assert window_is_default(DEFAULT_SINCE, "7.days") is False

    def test_a_one_day_override_still_counts_as_an_override(self) -> None:
        # Compared as written, not resolved to dates. The question is whether
        # a human overrode the assumption, not how far they moved it.
        assert window_is_default(DEFAULT_SINCE, "89.days") is False

    def test_a_widened_lookback_is_not_default_either(self) -> None:
        # Widening --since is harmless to the assumption but it still changes
        # the population, so it is still recorded.
        assert window_is_default("5.years", DEFAULT_UNTIL) is False


class TestTheWindowIsRecorded:
    """A reader must be able to tell which population produced a number."""

    def test_the_window_appears_in_the_summary(self) -> None:
        summary = summarize_rows(
            _publishable_rows(), MIN_ELIGIBLE_SAMPLE,
            window=("5.years", "30.days"),
        )
        assert summary["selection_window"] == {
            "since": "5.years", "until": "30.days"
        }
        assert summary["selection_window_is_default"] is False

    def test_an_omitted_window_records_the_defaults(self) -> None:
        # Callers that predate the parameter must not produce an artifact
        # that looks like it was measured over an unknown window.
        summary = summarize_rows(_publishable_rows(), MIN_ELIGIBLE_SAMPLE)
        assert summary["selection_window"] == {
            "since": DEFAULT_SINCE, "until": DEFAULT_UNTIL
        }
        assert summary["selection_window_is_default"] is True

    def test_the_default_window_is_marked_default(self) -> None:
        summary = summarize_rows(
            _publishable_rows(), MIN_ELIGIBLE_SAMPLE,
            window=(DEFAULT_SINCE, DEFAULT_UNTIL),
        )
        assert summary["selection_window_is_default"] is True

    def test_the_window_note_explains_the_tradeoff(self) -> None:
        summary = summarize_rows(_publishable_rows(), MIN_ELIGIBLE_SAMPLE)
        note = summary["WINDOW_NOTE"]
        assert "settling time" in note
        assert "not be compared" in note


class TestTheCaveatTravelsWithTheSentence:
    """The JSON is not what gets copied into a README. The sentence is."""

    def test_a_default_window_adds_no_caveat(self) -> None:
        sentence = describe(
            summarize_rows(
                _publishable_rows(), MIN_ELIGIBLE_SAMPLE,
                window=(DEFAULT_SINCE, DEFAULT_UNTIL),
            )
        )
        assert "non-default" not in sentence

    def test_a_narrowed_window_caveats_the_zero_finding_sentence(self) -> None:
        sentence = describe(
            summarize_rows(
                _publishable_rows(), MIN_ELIGIBLE_SAMPLE,
                window=("5.years", "7.days"),
            )
        )
        assert "non-default selection window" in sentence
        assert "until=7.days" in sentence
        assert "Not comparable" in sentence

    def test_the_caveat_survives_a_non_zero_rate(self) -> None:
        rows = _publishable_rows()
        rows[0] = _measured(reported=1)
        sentence = describe(
            summarize_rows(
                rows, MIN_ELIGIBLE_SAMPLE, window=("5.years", "30.days")
            )
        )
        assert "candidate false-positive rate" in sentence
        assert "non-default selection window" in sentence

    def test_a_withheld_rate_carries_no_window_caveat(self) -> None:
        # Nothing was published, so there is nothing to qualify. Appending a
        # comparability warning to a sentence that reports no number would
        # imply a number exists.
        sentence = describe(
            summarize_rows(
                [_measured()], 10, window=("5.years", "7.days")
            )
        )
        assert "No false-positive rate" in sentence
        assert "non-default" not in sentence


class TestTheOlderGuaranteesStillHold:
    """Adding a parameter must not move a gate two earlier PRs established."""

    def test_the_eighty_percent_completion_floor_is_unchanged(self) -> None:
        rows = [_measured() for _ in range(8)]
        summary = summarize_rows(rows, 10)
        assert summary["completion_rate"] == 0.8
        assert summary["gate_ready"] is True

    def test_the_sample_floor_still_withholds_at_eight(self) -> None:
        rows = [_measured() for _ in range(8)]
        summary = summarize_rows(rows, 10)
        assert summary["sample_floor_met"] is False
        assert summary["publishable"] is False

    def test_the_rule_of_three_bound_is_unchanged_at_twenty(self) -> None:
        summary = summarize_rows(_publishable_rows(20), 20)
        assert summary["false_positive_rate"] == 0.0
        assert summary["false_positive_rate_upper_bound_95"] == 0.15
