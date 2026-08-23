"""Tests for exit code and catch direction invariants.

Rules tested:
1. exit_code_for(v) and catch_direction_for(v) are the single source of truth
   used by production code (verify_test) and tested here.
2. Invariant: exit_code_for(v) == 0 <==> catch_direction_for(v) != "none".
3. COLLECTION_CATCH must fail closed: exit_code_for(COLLECTION_CATCH) == 1
   and catch_direction_for(COLLECTION_CATCH) == "none".
4. End-to-end: verify_test() on a fixture producing COLLECTION_CATCH returns
   exit_code 1 and evidence["catch_direction"] == "none".
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from jittest.diff import git_env
from jittest.verify import (
    VerdictClass,
    catch_direction_for,
    exit_code_for,
    verify_test,
)

# Collect all uppercase class attributes as the set of verdict classes.
_ALL_VERDICT_ATTRS = [
    attr for attr in dir(VerdictClass) if not attr.startswith("_") and attr.isupper()
]


@pytest.mark.parametrize("verdict_attr", _ALL_VERDICT_ATTRS)
def test_exit_code_invariant_pure_functions(verdict_attr: str) -> None:
    """Assert the exit-code/direction invariant using the PRODUCTION pure functions."""
    verdict = getattr(VerdictClass, verdict_attr)

    code = exit_code_for(verdict)
    direction = catch_direction_for(verdict)

    # Core invariant: exit code 0 <==> catch direction is not "none"
    assert (code == 0) == (direction != "none"), (
        f"Invariant broken for {verdict_attr} ({verdict}): "
        f"exit_code_for={code}, catch_direction_for={direction}"
    )


@pytest.mark.parametrize("verdict_attr", _ALL_VERDICT_ATTRS)
def test_proven_catch_contracts(verdict_attr: str) -> None:
    """Only PROVEN_CATCH and REPRODUCTION_CATCH may exit 0."""
    verdict = getattr(VerdictClass, verdict_attr)

    code = exit_code_for(verdict)
    direction = catch_direction_for(verdict)

    if verdict in (VerdictClass.PROVEN_CATCH, VerdictClass.REPRODUCTION_CATCH):
        assert code == 0, f"Expected exit code 0 for {verdict}"
        assert direction in ("regression", "reproduction"), (
            f"Expected non-none direction for {verdict}, got {direction}"
        )
    else:
        assert code == 1, (
            f"Expected fail-closed exit code 1 for non-proven verdict {verdict}"
        )
        assert direction == "none", (
            f"Expected direction 'none' for non-proven verdict {verdict}, got {direction}"
        )


def test_collection_catch_fails_closed() -> None:
    """COLLECTION_CATCH specifically must fail closed (exit 1, direction none)."""
    assert exit_code_for(VerdictClass.COLLECTION_CATCH) == 1, (
        "COLLECTION_CATCH must fail closed with exit code 1"
    )
    assert catch_direction_for(VerdictClass.COLLECTION_CATCH) == "none", (
        "COLLECTION_CATCH must have catch_direction 'none'"
    )


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True,
        text=True,
        check=True,
        env=git_env(),
    )
    return res.stdout.strip()


def test_collection_catch_e2e_fails_closed() -> None:
    """End-to-end: verify_test on a COLLECTION_CATCH fixture returns exit 1."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = Path(tmp_dir) / "repo"
        repo.mkdir()

        _git(repo, "init")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "commit.gpgsign", "false")

        # Base commit: valid passing module & test
        src_file = repo / "calc.py"
        src_file.write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        test_file = repo / "test_calc.py"
        test_file.write_text(
            "from calc import add\ndef test_add():\n    assert add(1, 2) == 3\n",
            encoding="utf-8",
        )

        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "base clean")
        base_sha = _git(repo, "rev-parse", "HEAD")

        # Head commit: syntax error causing collection breakage
        src_file.write_text(
            "def add(a, b):\n    return syntax error here <<<\n", encoding="utf-8"
        )
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "head broken collection")
        head_sha = _git(repo, "rev-parse", "HEAD")

        evidence, exit_code = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_file,
            no_sandbox=True,
        )

        # Must be classified as COLLECTION_CATCH
        assert evidence["verdict"] == VerdictClass.COLLECTION_CATCH
        assert evidence["proven_catch"] is False
        assert evidence["catch_direction"] == "none"

        # Crucial: exit_code MUST be 1 (fail closed)
        assert exit_code == 1, (
            f"Expected exit_code 1 for COLLECTION_CATCH, got {exit_code}"
        )
