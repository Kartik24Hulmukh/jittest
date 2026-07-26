"""Test helpers: build a throwaway git repository containing a real regression.

The fixture is deliberately a *behavioural* regression rather than a crash: the
buggy version returns a negative price instead of clamping at zero. That is
exactly the class of change type checkers, linters and coverage gates all wave
through, and exactly the class jittest exists to catch.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

BASE_SOURCE = '''\
"""A tiny pricing module."""


def apply_discount(price, percent):
    """Return the price after a percentage discount, never below zero."""
    if percent < 0:
        raise ValueError("percent must not be negative")
    discounted = price - (price * percent / 100.0)
    if discounted < 0:
        return 0.0
    return discounted


def total(items):
    return sum(items)
'''

# The regression: the clamp is gone. Everything else looks like a tidy-up.
HEAD_SOURCE = '''\
"""A tiny pricing module."""


def apply_discount(price, percent):
    """Return the price after a percentage discount, never below zero."""
    if percent < 0:
        raise ValueError("percent must not be negative")
    discounted = price - (price * percent / 100.0)
    return round(discounted, 2)


def total(items):
    return sum(items)
'''

CATCHING_TEST = '''\
from calc import apply_discount


def test_discount_never_goes_below_zero():
    assert apply_discount(100.0, 150.0) == 0.0
'''

HARDENING_TEST = '''\
from calc import apply_discount


def test_discount_of_ten_percent():
    assert apply_discount(100.0, 10.0) == 90.0
'''

BROKEN_TEST = '''\
from nonexistent_module_xyz import nothing


def test_cannot_import():
    assert nothing() == 1
'''

FLAKY_TEST = '''\
import os

_COUNTER = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flaky_counter")


def test_alternates():
    n = 0
    if os.path.exists(_COUNTER):
        with open(_COUNTER) as fh:
            n = int(fh.read() or 0)
    with open(_COUNTER, "w") as fh:
        fh.write(str(n + 1))
    assert n % 2 == 1
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=tests@jittest.dev",
         "-c", "user.name=jittest tests",
         "-c", "commit.gpgsign=false",
         *args],
        capture_output=True, text=True, check=True,
    )


class FixtureRepo:
    """A two-commit repo: base is correct, head contains one regression."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="jittest-fixture-"))
        self.base = ""
        self.head = ""

    def __enter__(self) -> FixtureRepo:
        _git(self.path, "init", "--quiet", "-b", "main")
        (self.path / "calc.py").write_text(BASE_SOURCE, encoding="utf-8")
        (self.path / "README.md").write_text("fixture\n", encoding="utf-8")
        _git(self.path, "add", ".")
        _git(self.path, "commit", "--quiet", "-m", "base: clamp discounts at zero")
        self.base = _git(self.path, "rev-parse", "HEAD").stdout.strip()

        (self.path / "calc.py").write_text(HEAD_SOURCE, encoding="utf-8")
        _git(self.path, "add", ".")
        _git(self.path, "commit", "--quiet", "-m",
             "refactor: round the discounted price")
        self.head = _git(self.path, "rev-parse", "HEAD").stdout.strip()
        return self

    def __exit__(self, *exc: object) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
