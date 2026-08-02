"""The R12 numbers, pinned to the conclusion they actually support.

Lane R12 produced good data and one wrong sentence. The data: 26 unmeasured
flask PRs with top risk scores of min 0.0000, median 0.0577, max 0.3969,
against a threshold of 0.35. The sentence: "clustered just under the 0.35
threshold ... rather than being far below it", supported by quoting 0.3272 and
0.3200 - the two largest values in the sample.

The distance from that sentence to "so let us try 0.30" is one meeting. These
tests make the arithmetic answer the question instead.

They also pin the two defects that were sitting in the same tables unremarked:
a maximum above the cutoff (which means the bucket was contaminated) and six
of ten rows reporting zero extracted functions on multi-thousand-line diffs
that had already passed the Python eligibility screen.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.failure_taxonomy import (  # noqa: E402
    ALL_BELOW_THRESHOLD,
    CAUSE_NOT_RECORDED,
    DEFAULT_RISK_THRESHOLD,
    NO_FUNCTIONS_EXTRACTED,
    SCORED_BUT_NOT_ANALYSED,
    ContaminatedPopulation,
    classify_row,
    distribution_verdict,
    extraction_disagreements,
    reasons,
)


# The 26 flask top-scores as characterised in Lane R12. Reconstructed to the
# reported five-number summary: min 0.0000, median 0.0577, max 0.3969, with
# the non-zero core-file scores spanning 0.1154 to 0.3272. The exact interior
# values are not the point; the shape is, and the shape is what the wrong
# sentence was written about.
FLASK_UNMEASURED_SCORES = [
    0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
    0.0000, 0.0000, 0.0000, 0.0000, 0.0000,
    0.1154, 0.1154, 0.1400, 0.1800, 0.2347, 0.2400, 0.2900,
    0.3200, 0.3272, 0.3272, 0.3400, 0.3969, 0.3969,
]


def _row(**extra: object) -> dict:
    row = {
        "base": "aaaaaaaa",
        "head": "bbbbbbbb",
        "model_requests": 0,
        "python_files_changed": 3,
        "functions_extracted": 2,
        "top_risk_score": 0.10,
    }
    row.update(extra)
    return row


import pytest


class TestTheMedianDecidesNotTheMaximum:
    """The whole module exists for this class."""

    def test_the_real_flask_distribution_is_far_below(self) -> None:
        # This is the test that matters. Same numbers, opposite conclusion to
        # the one that was written about them.
        verdict = distribution_verdict(FLASK_UNMEASURED_SCORES, threshold=0.40)
        assert verdict["verdict"] == "far_below_threshold"
        assert verdict["median"] < 0.10

    def test_the_flask_median_matches_the_reported_summary(self) -> None:
        verdict = distribution_verdict(FLASK_UNMEASURED_SCORES, threshold=0.40)
        assert verdict["min"] == 0.0
        assert verdict["median"] == 0.0577
        assert verdict["max"] == 0.3969

    def test_the_sentence_refuses_to_call_it_narrowly_missed(self) -> None:
        sentence = distribution_verdict(FLASK_UNMEASURED_SCORES, threshold=0.40)["sentence"]
        assert "nowhere near the cutoff" in sentence
        assert "not narrowly" in sentence

    def test_the_sentence_warns_against_quoting_the_maximum(self) -> None:
        sentence = distribution_verdict(FLASK_UNMEASURED_SCORES, threshold=0.40)["sentence"]
        assert "describes one row, not the sample" in sentence

    def test_a_genuinely_near_population_is_called_near(self) -> None:
        near = [0.30, 0.31, 0.32, 0.33, 0.34]
        verdict = distribution_verdict(near)
        assert verdict["verdict"] == "clustered_near_threshold"
        assert "legitimate question to open" in verdict["sentence"]

    def test_two_high_outliers_cannot_carry_a_low_sample(self) -> None:
        skewed = [0.0] * 20 + [0.3272, 0.3400]
        assert distribution_verdict(skewed)["verdict"] == "far_below_threshold"

    def test_zero_scores_stay_in_the_population(self) -> None:
        clean_scores = [s for s in FLASK_UNMEASURED_SCORES if s < 0.35]
        verdict = distribution_verdict(clean_scores)
        assert verdict["zero_score_rows"] == 13
        assert verdict["n"] == 24

    def test_an_empty_population_says_nothing(self) -> None:
        verdict = distribution_verdict([])
        assert verdict["verdict"] == "no_scores"
        assert verdict["n"] == 0



class TestAScoreAboveTheCutoffIsNotARankingRejection:
    """0.3969 > 0.35. Two rows in a ten-row sample. Nobody flagged it."""

    def test_the_flask_population_raises_contaminated_population(self) -> None:
        with pytest.raises(ContaminatedPopulation):
            distribution_verdict(FLASK_UNMEASURED_SCORES)

    def test_passing_analysed_rows_raises(self) -> None:
        with pytest.raises(ContaminatedPopulation):
            distribution_verdict([0.1, 0.2, 0.35, 0.4])

    def test_passing_unmeasured_rows_returns_verdict(self) -> None:
        verdict = distribution_verdict([0.0, 0.1, 0.2, 0.34])
        assert verdict["verdict"] in ("far_below_threshold", "clustered_near_threshold")
        assert "sentence" in verdict

    def test_a_clean_population_is_not_flagged(self) -> None:
        verdict = distribution_verdict([0.0, 0.1, 0.2, 0.34])
        assert verdict["population_contaminated"] is False
        assert verdict["at_or_above_threshold_rows"] == 0

    def test_such_a_row_classifies_as_scored_not_rejected(self) -> None:
        row = _row(top_risk_score=0.3969, functions_extracted=1)
        assert classify_row(row) == SCORED_BUT_NOT_ANALYSED


class TestExtractionAndScreeningMustAgree:
    """Six of ten rows: 2000+ insertions, Python touched, zero functions."""

    def test_zero_functions_on_a_python_diff_is_its_own_cause(self) -> None:
        row = _row(python_files_changed=12, functions_extracted=0)
        assert classify_row(row) == NO_FUNCTIONS_EXTRACTED

    def test_it_is_never_reported_as_a_ranking_failure(self) -> None:
        row = _row(python_files_changed=12, functions_extracted=0)
        assert classify_row(row) != ALL_BELOW_THRESHOLD

    def test_disagreeing_rows_are_listed_with_their_shas(self) -> None:
        rows = [
            _row(base="258d68b6", head="68936208",
                 python_files_changed=9, functions_extracted=0),
            _row(base="06ea505c", head="9368fb3f",
                 python_files_changed=1, functions_extracted=1),
        ]
        found = extraction_disagreements(rows)
        assert len(found) == 1
        assert found[0]["base"] == "258d68b6"

    def test_no_python_and_no_functions_is_not_a_disagreement(self) -> None:
        row = _row(python_files_changed=0, functions_extracted=0)
        assert classify_row(row) == CAUSE_NOT_RECORDED


class TestTheTaxonomyRefusesToGuess:
    def test_a_measured_row_has_no_cause(self) -> None:
        assert classify_row(_row(model_requests=4)) is None

    def test_a_missing_score_is_not_a_low_score(self) -> None:
        row = _row(top_risk_score=None, functions_extracted=2)
        assert classify_row(row) == CAUSE_NOT_RECORDED

    def test_a_missing_function_count_is_not_zero_functions(self) -> None:
        row = _row(functions_extracted=None)
        assert classify_row(row) == CAUSE_NOT_RECORDED

    def test_a_real_low_score_is_a_ranking_rejection(self) -> None:
        row = _row(top_risk_score=0.3272, functions_extracted=1)
        assert classify_row(row) == ALL_BELOW_THRESHOLD

    def test_reasons_orders_by_count(self) -> None:
        rows = [
            _row(top_risk_score=0.10, functions_extracted=1),
            _row(top_risk_score=0.11, functions_extracted=1),
            _row(python_files_changed=5, functions_extracted=0),
        ]
        buckets = reasons(rows)
        assert list(buckets) == [ALL_BELOW_THRESHOLD, NO_FUNCTIONS_EXTRACTED]
        assert buckets[ALL_BELOW_THRESHOLD] == 2

    def test_the_threshold_is_the_production_default(self) -> None:
        assert DEFAULT_RISK_THRESHOLD == 0.35
