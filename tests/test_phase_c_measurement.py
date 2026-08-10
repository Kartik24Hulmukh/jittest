"""Tests verifying Phase C Execution Ledger and Measurement Report Integrity."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LEDGER_PATH = REPO_ROOT / "phase-c-execution-ledger.json"
REPORT_PATH = REPO_ROOT / "phase-c-measurement-report.json"


def test_phase_c_execution_ledger_structure():
    assert LEDGER_PATH.exists(), "phase-c-execution-ledger.json must exist"
    data = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert "protocol_commit" in data
    assert "entries" in data

    entries = data["entries"]
    assert len(entries) == 83, f"Expected 83 entries in ledger, got {len(entries)}"

    calib = [e for e in entries if e["cohort"] == "calibration"]
    bug_h = [e for e in entries if e["cohort"] == "bug_holdout"]
    ctrl_h = [e for e in entries if e["cohort"] == "control_holdout"]

    assert len(calib) == 7
    assert len(bug_h) == 16
    assert len(ctrl_h) == 60


def test_phase_c_measurement_report_metrics():
    assert REPORT_PATH.exists(), "phase-c-measurement-report.json must exist"
    data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["model"] == "mistral/codestral-2508"
    assert data["endpoint"] == "https://api.mistral.ai/v1/chat/completions"
    assert data["prompt_version"] == "v1.4"

    metrics = data["metrics"]
    assert "catch_rate" in metrics
    assert "false_positive_rate" in metrics
    assert "cost_per_pr_usd" in metrics
    assert metrics["total_eval_rows"] == 83

    dispositions = data["dispositions"]
    assert dispositions["calibration"]["total"] == 7
    assert dispositions["bug_holdouts"]["total"] == 16
    assert dispositions["control_holdouts"]["total"] == 60
