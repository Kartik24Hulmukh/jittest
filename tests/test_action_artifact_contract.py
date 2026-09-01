"""Regression tests for the public composite Action contract."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_custom_output_directory_is_uploaded():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "JITTEST_OUTPUT_DIR: ${{ inputs.output-dir }}" in action
    assert "path: ${{ inputs.output-dir }}/" in action
    assert "path: jittest-evidence/" not in action


def test_missing_evidence_is_not_silently_ignored():
    action = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "if-no-files-found: warn" in action
    assert "if-no-files-found: ignore" not in action


def test_quickstart_keeps_untrusted_prs_fail_closed():
    quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "persist-credentials: false" in quickstart
    assert 'sandbox-mode: "required"' in quickstart
    assert 'policy: "advisory"' in quickstart
    assert "@v0.3.2" not in quickstart
