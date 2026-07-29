"""A minimal pytest-compatible shim, used only when pytest is not importable.

jittest runs candidate tests inside other people's CI with the mini-runner
when pytest is absent. Candidates, and the conftest.py files they rely on,
almost always begin with ``import pytest`` - for ``fixture``, ``raises``,
``approx``, ``mark``, ``MonkeyPatch``. Without this shim that import fails and
the candidate dies at collection, so in a pytest-native repository jittest
silently catches nothing and cannot say why (roadmap P3-2).

This facade re-exports the shim surface from _pytestshim_core (fixture/mark
machinery) and _pytestshim_helpers (raises/approx/MonkeyPatch/capture), and
_minirunner installs it as sys.modules["pytest"] only when no real pytest can
be imported. It is NOT a pytest replacement: anything unsupported fails loudly
rather than silently passing or skipping.
"""
from __future__ import annotations

import importlib.util
import sys

from ._pytestshim_core import (
    FIXTURE_MARKER,
    MARKS_ATTR,
    Failed,
    FixtureDef,
    FixtureRequest,
    Skipped,
    XFailed,
    fail,
    fixture,
    importorskip,
    mark,
    param,
    skip,
    xfail,
)
from ._pytestshim_helpers import (
    Approx,
    CaptureFixture,
    CaptureResult,
    MonkeyPatch,
    RaisesContext,
    approx,
    raises,
)

__version__ = "0.0.0-jittest-shim"

__all__ = [
    "Approx", "CaptureFixture", "CaptureResult", "FIXTURE_MARKER", "Failed",
    "FixtureDef", "FixtureRequest", "MARKS_ATTR", "MonkeyPatch",
    "RaisesContext", "Skipped", "XFailed", "approx", "fail", "fixture",
    "importorskip", "install", "is_real_pytest_available", "mark", "param",
    "raises", "skip", "xfail",
]


def is_real_pytest_available() -> bool:
    try:
        spec = importlib.util.find_spec("pytest")
    except (ImportError, ValueError):
        return False
    if spec is None or spec.origin is None:
        return False
    # Never mistake ourselves for the real thing.
    return "jittest" not in str(spec.origin)


def install() -> bool:
    """Install this module as sys.modules["pytest"]. Returns True if installed."""
    if is_real_pytest_available():
        return False
    module = sys.modules.get(__name__)
    if module is None:
        # Loaders that never registered us, or tests that scrub jittest* from
        # sys.modules: rebuild a module object from our own globals, which
        # always exist where this code runs.
        import types
        module = types.ModuleType(__name__)
        module.__dict__.update({k: v for k, v in globals().items()
                                if not k.startswith("__")})
    sys.modules["pytest"] = module
    return True
