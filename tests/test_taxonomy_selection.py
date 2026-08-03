"""The contamination guard has to be satisfiable, or the caller routes around it.

A fatal guard that no correct caller can satisfy does not get respected. It
gets a bare ``except`` around it, or a caller that quietly filters its input
until the exception stops happening - and filtering until the error goes away
is exactly how the Session T population got contaminated in the first place.

So these tests are about the one row that decides it: unmeasured, and scored
above the cutoff. ``classify_row`` already calls that ``scored_but_not_analysed``
and has since PR #87. It is a legitimate member of the unmeasured population
and an illegitimate member of any statement about ranking, and both of those
facts have to hold at once.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - dependency-free ci.yml step
    raise unittest.SkipTest(
        "requires pytest; skipped by the zero-dependency unittest run in ci.yml"
    ) from exc

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.failure_taxonomy import (  # noqa: E402
    ContaminatedPopulation,
    distribution_verdict,
)
from eval.taxonomy_selection import (  # noqa: E402
    ranking_rejection_scores,
    verdict_for_rows,
)


def _unmeasured(score, functions=3, python_files=4, **extra):
    row = {
        "model_requests": 0,
        "functions_extracted": functions,
        "python_files_changed": python_files,
        "top_risk_score": score,
    }
    row.update(extra)
    return row


def _analysed(score):
    return {
        "model_requests": 12,
        "functions_extracted": 5,
        "python_files_changed": 4,
        "top_risk_score": score,
    }


class TestTheGuardMustBeSatisfiable:
    def test_a_high_scoring_unmeasured_row_does_not_break_the_caller(self):
        # Ranking said yes at 0.62; a target cap said no afterwards. Under the
        # bare guard this row makes the correct call raise. It must not.
        rows = [_unmeasured(0.62), _unmeasured(0.11), _unmeasured(0.04)]
        out = verdict_for_rows(rows)
        assert out["scored_but_not_analysed"] == 1
        assert out["ranking_rejections"] == 2
        assert out["verdict"]["n"] == 2

    def test_the_bare_guard_still_raises_on_that_same_score(self):
        # Proof the two tests above and below are describing the same value,
        # and that the protection was not removed - only given a caller.
        with pytest.raises(ContaminatedPopulation):
            distribution_verdict([0.62, 0.11, 0.04])

    def test_selection_never_yields_a_score_the_guard_would_reject(self):
        rows = [_unmeasured(v) for v in (0.62, 0.35, 0.3499, 0.0, 0.11)]
        scores = ranking_rejection_scores(rows)
        assert all(score < 0.35 for score in scores)
        assert 0.35 not in scores


class TestAnalysedRowsAreStillRefused:
    def test_analysed_rows_are_not_counted_as_unanalysed(self):
        rows = [_analysed(0.71), _analysed(0.55), _unmeasured(0.09)]
        out = verdict_for_rows(rows)
        assert out["rows_analysed"] == 2
        assert out["rows_unanalysed"] == 1
        assert out["verdict"]["n"] == 1

    def test_a_population_of_only_analysed_rows_describes_nothing(self):
        out = verdict_for_rows([_analysed(0.71), _analysed(0.55)])
        assert out["verdict"]["verdict"] == "no_scores"
        assert out["rows_unanalysed"] == 0


class TestTheVerdictDeclaresHowNarrowItIs:
    def test_excluded_rows_are_reported_not_absorbed(self):
        rows = [
            _unmeasured(0.05),
            _unmeasured(0.08),
            _unmeasured(0.12),
            _unmeasured(0.90),
            _unmeasured(None, functions=0, python_files=27),
            _unmeasured(0.40),
        ]
        out = verdict_for_rows(rows)
        assert out["rows_unanalysed"] == 6
        assert out["ranking_rejections"] == 3
        assert out["scored_but_not_analysed"] == 2
        assert out["no_functions_extracted"] == 1
        # Half the population is outside the verdict. Say so numerically.
        assert out["excluded_from_verdict"] == 3

    def test_zeros_stay_in_the_ranking_population(self):
        rows = [_unmeasured(0.0), _unmeasured(0.0), _unmeasured(0.30)]
        out = verdict_for_rows(rows)
        assert out["verdict"]["zero_score_rows"] == 2
        assert out["verdict"]["median"] == 0.0
        assert out["verdict"]["verdict"] == "far_below_threshold"

    def test_a_missing_cause_is_never_rounded_into_a_ranking_rejection(self):
        rows = [_unmeasured(None, functions=None), _unmeasured(0.10)]
        out = verdict_for_rows(rows)
        assert out["cause_not_recorded"] == 1
        assert out["ranking_rejections"] == 1
        assert out["verdict"]["n"] == 1
