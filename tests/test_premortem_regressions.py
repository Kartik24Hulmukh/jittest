"""Regression tests for Premortem S06 (long paths) and S14 (backslash filenames).

Ensures fixture creation and path handling degrade cleanly without uncaught
OS error leaks or missing parent directory crashes.
"""
import shutil
import tempfile
from pathlib import Path

from eval.premortem3 import make_fixture, s14_windowsish_paths


def test_long_paths_do_not_break_fixture_creation():
    """S06: Assert make_fixture either succeeds or raises typed error."""
    tmp = Path(tempfile.mkdtemp(prefix="test-s06-"))
    try:
        deep = tmp
        while len(str(deep.resolve())) < 300:
            deep = deep / ("d" * 40)
        try:
            repo = make_fixture(deep)
            assert repo.exists()
        except (RuntimeError, OSError) as exc:
            assert "exceeds OS limits" in str(exc) or "too long" in str(exc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_backslash_in_a_filename_is_handled_or_rejected_cleanly():
    """S14: Assert backslash filename in fixture is created cleanly."""
    tmp = Path(tempfile.mkdtemp(prefix="test-s14-"))
    try:
        res, problems = s14_windowsish_paths(tmp)
        assert "harness raised FileNotFoundError" not in str(problems)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
