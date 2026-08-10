"""Tests verifying Phase C Calibration Ledger and Report Integrity."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CALIB_LEDGER_PATH = REPO_ROOT / "phase-c-calibration-ledger.json"
CALIB_REPORT_PATH = REPO_ROOT / "phase-c-calibration-report.json"
EXEC_LEDGER_PATH = REPO_ROOT / "phase-c-execution-ledger.json"
MEAS_REPORT_PATH = REPO_ROOT / "phase-c-measurement-report.json"


def test_phase_c_calibration_artifacts_exist_separately():
    assert CALIB_LEDGER_PATH.exists(), "phase-c-calibration-ledger.json must exist"
    assert CALIB_REPORT_PATH.exists(), "phase-c-calibration-report.json must exist"
    # Verify Sweep 1 artifacts were preserved intact (Defect 5)
    assert EXEC_LEDGER_PATH.exists(), "phase-c-execution-ledger.json must be preserved"
    assert MEAS_REPORT_PATH.exists(), "phase-c-measurement-report.json must be preserved"


def test_phase_c_calibration_ledger_structure():
    data = json.loads(CALIB_LEDGER_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert "protocol_commit" in data
    assert "entries" in data

    entries = data["entries"]
    assert len(entries) == 7, f"Expected 7 calibration entries in ledger, got {len(entries)}"

    calib = [e for e in entries if e["cohort"] == "calibration"]
    assert len(calib) == 7

    # Defect 3: Assert zero inverted_range statuses
    inverted = [e for e in entries if e.get("diff_status") == "inverted_range"]
    assert len(inverted) == 0, f"Expected 0 inverted_range statuses, got {len(inverted)}"


def test_phase_c_calibration_report_metrics():
    data = json.loads(CALIB_REPORT_PATH.read_text(encoding="utf-8"))

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
