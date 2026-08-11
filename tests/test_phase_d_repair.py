"""Unit tests for Phase D mechanical repair & AST assertion preservation."""

from jittest.phase_d.repair import extract_assertion_fingerprints, verify_assertion_preservation


def test_assertion_fingerprint_extraction():
    code = """import pytest

def test_example():
    val = calc(10)
    assert val == 20
    with pytest.raises(ValueError):
        calc(-1)
"""
    fps = extract_assertion_fingerprints(code)
    assert len(fps) == 2
    assert any("Assert" in fp for fp in fps)
    assert any("PytestRaises" in fp for fp in fps)


def test_assertion_preservation_rejects_removed_assertions():
    original = "def test_f():\n    assert foo() == 42\n"
    valid_repair = "import sys\ndef test_f():\n    assert foo() == 42\n"
    invalid_repair = "def test_f():\n    pass\n"

    assert verify_assertion_preservation(original, valid_repair)
    assert not verify_assertion_preservation(original, invalid_repair)
