"""Unit test for Phase D Confirmatory Holdout harness."""

from eval.phase_d_holdout import run_confirmatory_holdout


def test_confirmatory_holdout_runs():
    report = run_confirmatory_holdout()

    assert report["schema_version"] == "1.0"
    assert report["bug_rows_evaluated"] == 16
    assert report["control_rows_evaluated"] == 60
    assert "launch_gate_passed" in report
