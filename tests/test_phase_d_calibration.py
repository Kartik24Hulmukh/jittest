"""Unit test for Phase D Fresh Calibration harness."""

from eval.phase_d_calibration import run_fresh_calibration


def test_fresh_calibration_runs():
    report = run_fresh_calibration()

    assert report["schema_version"] == "1.0"
    assert report["bug_rows_evaluated"] == 10
    assert report["control_rows_evaluated"] == 20
    assert "calibration_gate_passed" in report
