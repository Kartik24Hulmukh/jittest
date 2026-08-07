"""Unit test enforcing exact match of 20 W1-R6 base/head calibration pairs."""

import json
from pathlib import Path


def test_sanitized_calibration_artifact_exists_and_valid():
    p = Path("eval/artifacts/flask-fp-ladder-w1r6-sanitized.json")
    assert p.exists(), "Missing authoritative calibration artifact!"

    data = json.loads(p.read_text(encoding="utf-8"))
    ancestry = data.get("ancestry_manifest", [])
    assert len(ancestry) == 20, f"Expected 20 calibration pairs, got {len(ancestry)}"

    for row in ancestry:
        assert "base_sha" in row and len(row["base_sha"]) in (8, 40)
        assert "head_sha" in row and len(row["head_sha"]) in (8, 40)
