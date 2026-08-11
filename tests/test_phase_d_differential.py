"""Unit tests for Phase D DifferentialExplorer."""

from jittest.phase_d.differential import DifferentialExplorer, ExecutionTrace, PairedResult


def test_differential_explorer_deduplication():
    explorer = DifferentialExplorer()
    code = "def test_foo(): pass\n"

    assert not explorer.is_duplicate(code)
    assert explorer.is_duplicate(code)


def test_paired_result_difference_detection():
    t_pass = ExecutionTrace(outcome="PASS", return_value_repr="42", target_reached=True)
    t_fail = ExecutionTrace(outcome="FAIL_EXCEPTION", exception_type="ValueError", exception_message="invalid", target_reached=True)

    pr_diff = PairedResult(candidate_sha="sha1", base_trace=t_pass, head_trace=t_fail)
    assert not pr_diff.is_identical
    assert pr_diff.has_paired_difference

    pr_same = PairedResult(candidate_sha="sha2", base_trace=t_pass, head_trace=t_pass)
    assert pr_same.is_identical
    assert not pr_same.has_paired_difference
