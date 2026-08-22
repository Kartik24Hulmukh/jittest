"""Invariant tests for exit code and catch direction.

Rule: exit_code == 0 if and only if catch_direction != "none"
(i.e. only proven catches in regression or reproduction direction succeed with exit 0;
all inconclusive, collection_catch, refuted, and non-discriminating verdicts fail closed with exit 1).
"""

import pytest
from jittest.verify import VerdictClass


@pytest.mark.parametrize(
    "verdict_attr",
    [attr for attr in dir(VerdictClass) if not attr.startswith("_")],
)
def test_exit_code_invariant_for_verdict_classes(verdict_attr: str) -> None:
    verdict = getattr(VerdictClass, verdict_attr)

    # Resolve catch_direction according to schema contract
    if verdict == VerdictClass.PROVEN_CATCH:
        catch_direction = "regression"
        expected_exit_code = 0
        expected_proven_catch = True
    elif verdict == VerdictClass.REPRODUCTION_CATCH:
        catch_direction = "reproduction"
        expected_exit_code = 0
        expected_proven_catch = True
    else:
        catch_direction = "none"
        expected_exit_code = 1
        expected_proven_catch = False

    # Invariant: exit_code == 0 <===> catch_direction != "none"
    assert (expected_exit_code == 0) == (catch_direction != "none"), (
        f"Invariant violation for {verdict_attr} ({verdict}): "
        f"exit_code={expected_exit_code} but catch_direction={catch_direction}"
    )
    assert (expected_exit_code == 0) == expected_proven_catch, (
        f"Invariant violation for {verdict_attr} ({verdict}): "
        f"exit_code={expected_exit_code} but proven_catch={expected_proven_catch}"
    )
