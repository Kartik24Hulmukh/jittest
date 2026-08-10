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
    assert len(entries) == 7, f"Expected 7 calibration entries in ledger, got {len(entries)}"

    calib = [e for e in entries if e["cohort"] == "calibration"]
    assert len(calib) == 7


def test_phase_c_measurement_report_metrics():
    assert REPORT_PATH.exists(), "phase-c-measurement-report.json must exist"
    data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["model"] == "mistral/codestral-2508"
    assert data["endpoint"] == "https://api.mistral.ai/v1/chat/completions"
    assert data["prompt_version"] == "v1.4"

    metrics = data["metrics"]
    assert "calibration_catch_rate" in metrics
    assert "total_usd_spent" in metrics
    assert metrics["calibration_rows_evaluated"] == 7

    dispositions = data["dispositions"]
    assert dispositions["calibration"]["total"] == 7

    verdict = data["verdict"]
    assert verdict["holdout_pass_executed"] is False
