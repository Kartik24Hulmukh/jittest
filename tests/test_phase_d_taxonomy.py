"""Unit tests for Phase D failure taxonomy."""

from jittest.phase_d.taxonomy import Disposition


def test_disposition_values_and_helpers():
    assert Disposition.PARSE_FAILED == "parse_failed"
    assert Disposition.ACCEPTED_STRONG_CATCH == "accepted_strong_catch"

    assert Disposition.PARSE_FAILED.is_disqualified()
    assert Disposition.BASE_ASSERTION_FAILED.is_disqualified()
    assert not Disposition.ACCEPTED_STRONG_CATCH.is_disqualified()

    assert Disposition.ACCEPTED_STRONG_CATCH.is_catch()
    assert Disposition.STABLE_TECHNICAL_WEAK_CATCH.is_catch()
    assert not Disposition.HEAD_PASSED.is_catch()
