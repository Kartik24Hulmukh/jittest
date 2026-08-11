"""Unit test for Phase D Development Replay harness."""

from eval.phase_d_replay import run_development_replay


def test_development_replay_runs():
    report = run_development_replay()

    assert report["schema_version"] == "1.0"
    assert report["status"] == "exploratory_post_hoc"
    assert report["rows_evaluated"] == 7
    assert "development_gate_passed" in report
    assert len(report["rows"]) == 7
