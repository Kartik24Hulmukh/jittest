"""Regression tests for _clone_url in scripts/run_instance.py.

WO-22 D7: The clone URL must be a valid HTTPS URL without spurious braces.
"""

import sys
from pathlib import Path

# Make scripts/ importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from run_instance import _clone_url


def test_clone_url_pytest():
    assert _clone_url("pytest-dev/pytest") == "https://github.com/pytest-dev/pytest.git"


def test_clone_url_no_left_brace():
    assert "{" not in _clone_url("pytest-dev/pytest")


def test_clone_url_no_right_brace():
    assert "}" not in _clone_url("pytest-dev/pytest")


def test_clone_url_requests_starts_with_https():
    assert _clone_url("psf/requests").startswith("https://")


def test_clone_url_requests_full():
    assert _clone_url("psf/requests") == "https://github.com/psf/requests.git"


def test_clone_url_flask():
    assert _clone_url("pallets/flask") == "https://github.com/pallets/flask.git"
