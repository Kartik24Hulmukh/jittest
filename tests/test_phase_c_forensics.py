"""Tests verifying Phase C Calibration Forensics Export integrity."""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORENSICS_PATH = REPO_ROOT / "phase-c-calibration-forensics.json"


def test_phase_c_calibration_forensics_structure():
    assert FORENSICS_PATH.exists(), "phase-c-calibration-forensics.json must exist"
    data = json.loads(FORENSICS_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert "protocol_commit" in data
    assert "protocol_tree" in data
    assert "parent_sha" in data

    assert "verdict_reason_distribution" in data
    dist = data["verdict_reason_distribution"]
    assert sum(dist.values()) > 0

    assert "rows" in data
    rows = data["rows"]
    assert len(rows) == 7

    for rid in ["bug_flask_01", "bug_flask_04", "bug_flask_06"]:
        assert rid in rows
        row = rows[rid]
        assert "discarded_histogram" in row
        assert "candidates" in row
        candidates = row["candidates"]
        assert len(candidates) > 0
        # Assert representative rows have inlined code
        assert any("code" in c for c in candidates)
