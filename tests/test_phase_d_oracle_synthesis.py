"""Unit tests for Phase D OracleLastSynthesizer."""

from jittest.phase_d.oracle_synthesis import OracleLastSynthesizer, contains_volatile_token


def test_volatile_token_detection():
    assert contains_volatile_token("object at 0x7f9a8b1c")
    assert contains_volatile_token("id=123e4567-e89b-12d3-a456-426614174000")
    assert contains_volatile_token("date=2026-08-11")
    assert not contains_volatile_token("val = 42")


def test_oracle_code_validation():
    synth = OracleLastSynthesizer()
    valid_code = "def test_x():\n    assert foo() == 42\n"
    volatile_code = "def test_x():\n    assert str(obj) == '<Obj 0x7f9a8b1c>'\n"
    no_assertion_code = "def test_x():\n    foo()\n"

    assert synth.is_valid_oracle_code(valid_code)
    assert not synth.is_valid_oracle_code(volatile_code)
    assert not synth.is_valid_oracle_code(no_assertion_code)
