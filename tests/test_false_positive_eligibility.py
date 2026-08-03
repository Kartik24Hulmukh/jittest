"""A PR that changes no Python is not a failed measurement.

Background. #84 split ``no_model_requests`` by the funnel so a zero-request row
would name how far it got. The very next run finished the trace: the dominant
bucket became ``no_targets_after_ranking``, and the first row traced by hand
had changed exactly one file - ``.github/workflows/publish.yml``. No Python, no
functions, no targets. jittest was right. The harness scored it as a failure
and divided by it.

That is worse than the two bugs before it, because those withheld a number and
this one produced a wrong one that looked plausible: ``completion_rate 0.094``
over a denominator of 32 PRs that were mostly never eligible.

Screening the denominator is the fix and is also a trap, because a smaller
denominator makes the completion gate easier to clear. Three eligible PRs,
three measured, 1.00, green. ``TestTheFilterCannotBecomeALoophole`` is the
reason this file is longer than the change it guards.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.false_positives import (  # noqa: E402
    MIN_ELIGIBLE_SAMPLE,
    describe,
    is_python_path,
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


class TestEligibilityPredicate:
    def test_a_python_file_is_eligible(self):
        assert is_python_path("src/jittest/diff.py")

    def test_the_workflow_file_that_started_this_is_not(self):
        assert not is_python_path(".github/workflows/publish.yml")

    def test_docs_and_config_are_not(self):
        assert not is_python_path("README.md")
        assert not is_python_path("pyproject.toml")

    def test_a_stub_declares_no_behaviour_to_regress(self):
        assert not is_python_path("src/jittest/py.typed")
        assert not is_python_path("src/jittest/types.pyi")

    def test_a_notebook_is_not_read_by_the_diff_parser(self):
        assert not is_python_path("analysis/scratch.ipynb")

    def test_surrounding_whitespace_does_not_change_eligibility(self):
        assert is_python_path("  src/a.py  ")

    def test_a_filename_merely_containing_py_is_not_eligible(self):
        assert not is_python_path("docs/python-guide.md")


class TestScreenedOutStaysVisible:
    def test_the_ineligible_population_is_recorded(self):
        summary = summarize_rows(
            [_measured() for _ in range(20)], 20, screened_out=29
        )
        assert summary["prs_screened_out_as_ineligible"] == 29

    def test_an_unscreened_run_records_none_not_zero(self):
        """None means the run predates screening. Zero means none were found."""
        summary = summarize_rows([_measured()], 1)
        assert summary["prs_screened_out_as_ineligible"] is None

    def test_the_summary_says_the_published_bound_is_too_tight(self):
        summary = summarize_rows([_measured()], 1)
        assert "9.4%" in summary["ELIGIBILITY_NOTE"]
        assert "too tight" in summary["ELIGIBILITY_NOTE"]


class TestTheFilterCannotBecomeALoophole:
    def test_three_of_three_eligible_is_not_publishable(self):
        summary = summarize_rows([_measured() for _ in range(3)], 3)
        assert summary["completion_rate"] == 1.0
        assert summary["gate_ready"] is True
        assert summary["sample_floor_met"] is False
        assert summary["publishable"] is False

    def test_the_sentence_refuses_to_quote_a_rate_from_three(self):
        summary = summarize_rows([_measured() for _ in range(3)], 3)
        sentence = describe(summary)
        assert "below the floor" in sentence
        assert "%" not in sentence

    def test_the_floor_is_met_at_the_boundary(self):
        rows = [_measured() for _ in range(MIN_ELIGIBLE_SAMPLE)]
        summary = summarize_rows(rows, MIN_ELIGIBLE_SAMPLE)
        assert summary["sample_floor_met"] is True
        assert summary["publishable"] is True
        assert "95% confidence" in describe(summary)

    def test_the_floor_counts_measured_prs_not_selected_ones(self):
        """Selecting 20 and measuring 19 does not clear a floor of 20."""
        rows = [_measured() for _ in range(19)] + [{"model_requests": 0}]
        summary = summarize_rows(rows, 20)
        assert summary["gate_ready"] is True
        assert summary["sample_floor_met"] is False


class TestTheOldGateStillWorks:
    """#84 shipped these guarantees. Screening must not have moved them."""

    def test_the_completion_floor_is_still_eighty_percent(self):
        rows = [_measured() for _ in range(8)] + [{"model_requests": 0}] * 2
        summary = summarize_rows(rows, 10)
        assert summary["completion_rate"] == 0.8
        assert summary["gate_ready"] is True

    def test_a_collapsed_run_still_withholds_the_rate(self):
        rows = [_measured()] + [{"model_requests": 0}] * 9
        summary = summarize_rows(rows, 10)
        assert summary["gate_ready"] is False
        assert summary["false_positive_rate"] is None
