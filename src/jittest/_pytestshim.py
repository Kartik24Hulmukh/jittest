"""A minimal pytest-compatible shim, used only when pytest is not importable.

Why this exists: jittest runs candidate tests inside other people's CI with
the mini-runner when pytest is absent. Candidates, and the conftest.py files
they rely on, almost always begin with ``import pytest`` - for ``fixture``,
``raises``, ``approx``, ``mark``, ``MonkeyPatch``. Without this shim that
import fails and the candidate dies at collection, so in a pytest-native
repository jittest silently catches nothing and cannot say why (roadmap P3-2).

This is NOT a pytest replacement. It implements the small, load-bearing
surface that candidates and conftests actually use, with semantics chosen so
that anything unsupported fails loudly (collection error) rather than
silently passing or silently skipping:

  - fixture(scope=..., params=..., autouse=..., ids=...) markers
  - mark.skip / mark.skipif / mark.xfail / mark.parametrize
  - raises (with match=), approx, skip, fail, importorskip, param
  - MonkeyPatch with undo, and a FixtureRequest carrying param/fixturename

The runner (_minirunner) installs this module as sys.modules["pytest"] only
when a real pytest cannot be imported. If a real pytest is present it is
always preferred.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import os
import re
import sys
import unittest
from collections.abc import MutableMapping
from typing import Any, NamedTuple

__version__ = "0.0.0-jittest-shim"

FIXTURE_MARKER = "__jittest_fixture__"
MARKS_ATTR = "pytestmark"


class Skipped(unittest.SkipTest):
    """Raised by pytest.skip(); a unittest.SkipTest so the runner counts it
    as a skip, never as a pass."""


class Failed(AssertionError):
    """Raised by pytest.fail()."""


class XFailed(Exception):
    """Raised by pytest.xfail() inside a test body."""


def skip(reason: str = "") -> None:
    raise Skipped(reason)


def fail(reason: str = "") -> None:
    raise Failed(reason or "pytest.fail() called")


def xfail(reason: str = "") -> None:
    raise XFailed(reason)


def importorskip(module_name: str, reason: str | None = None) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError:
        raise Skipped(reason or f"could not import {module_name}") from None


# ---------------------------------------------------------------------------
# fixture marking
# ---------------------------------------------------------------------------

class FixtureDef:
    """The record _minirunner reads to resolve one fixture."""

    def __init__(self, fn, scope: str = "function", params=None,
                 autouse: bool = False, name: str | None = None, ids=None):
        self.fn = fn
        self.scope = scope if scope in ("function", "class", "module",
                                        "package", "session") else "function"
        self.params = list(params) if params is not None else None
        self.autouse = bool(autouse)
        self.name = name or getattr(fn, "__name__", "fixture")
        self.ids = list(ids) if ids is not None else None


def fixture(arg=None, *, scope: str = "function", params=None,
            autouse: bool = False, name: str | None = None, ids=None):
    """Usable as @fixture and @fixture(...).

    Marks the function with our own attribute AND the attribute real pytest
    uses, so _minirunner recognises fixtures declared with either library.
    """
    def wrap(fn):
        fdef = FixtureDef(fn, scope=scope, params=params, autouse=autouse,
                          name=name, ids=ids)
        setattr(fn, FIXTURE_MARKER, fdef)
        setattr(fn, "_pytestfixturefunction", fdef)
        return fn

    if callable(arg):
        return wrap(arg)
    return wrap


class param(NamedTuple):
    """pytest.param(value, id=...) for fixture params and parametrize."""
    values: Any
    id: str | None = None


# ---------------------------------------------------------------------------
# marks
# ---------------------------------------------------------------------------

class _Mark:
    def __init__(self, name: str, args: tuple, kwargs: dict):
        self.name = name
        self.args = args
        self.kwargs = kwargs


def _add_mark(obj, mark: _Mark):
    marks = list(getattr(obj, MARKS_ATTR, []))
    marks.append(mark)
    try:
        setattr(obj, MARKS_ATTR, marks)
    except (AttributeError, TypeError):
        pass
    return obj


class _MarkNamespace:
    def skip(self, arg=None, *, reason: str = ""):
        if callable(arg):
            return _add_mark(arg, _Mark("skip", (), {"reason": reason}))

        def deco(obj):
            return _add_mark(obj, _Mark("skip", (), {"reason": reason}))
        return deco

    def skipif(self, condition, *, reason: str = ""):
        def deco(obj):
            return _add_mark(obj, _Mark("skipif", (condition,), {"reason": reason}))
        return deco

    def xfail(self, condition=True, *, reason: str = "", strict: bool = False):
        def deco(obj):
            return _add_mark(obj, _Mark("xfail", (condition,),
                                        {"reason": reason, "strict": strict}))
        return deco

    def parametrize(self, argnames, argvalues, ids=None):
        names = [n.strip() for n in argnames.split(",")] if isinstance(
            argnames, str) else list(argnames)
        id_list = list(ids) if ids is not None else None

        def deco(fn):
            existing = list(getattr(fn, "__jittest_parametrize__", []))
            existing.append((names, list(argvalues), id_list))
            setattr(fn, "__jittest_parametrize__", existing)
            return fn
        return deco

    def __getattr__(self, name: str):
        # Unknown marks (slow, integration, ...) are recorded and ignored,
        # matching pytest's warn-but-run behaviour for unregistered marks.
        def recorder(*args, **kwargs):
            mark = _Mark(name, args, kwargs)
            if args and callable(args[0]) and len(args) == 1 and not kwargs:
                return _add_mark(args[0], mark)

            def deco(obj):
                return _add_mark(obj, mark)
            return deco
        return recorder


mark = _MarkNamespace()


# ---------------------------------------------------------------------------
# raises / approx
# ---------------------------------------------------------------------------

class RaisesContext:
    def __init__(self, expected, match: str | None = None):
        self.expected = expected
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise Failed(f"DID NOT RAISE {self._name()}")
        if not issubclass(exc_type, self.expected):
            return False
        self.value = exc
        if self.match is not None and not re.search(self.match, str(exc)):
            raise Failed(
                f"exception message {exc!r} does not match {self.match!r}")
        return True

    def _name(self):
        if isinstance(self.expected, tuple):
            return "(" + ", ".join(e.__name__ for e in self.expected) + ")"
        return getattr(self.expected, "__name__", str(self.expected))


def raises(expected, match: str | None = None) -> RaisesContext:
    return RaisesContext(expected, match)


class Approx:
    def __init__(self, expected, rel=None, abs=None):  # noqa: A002 - pytest API
        self.expected = expected
        self.rel = 1e-6 if rel is None else rel
        self.abs = 1e-12 if abs is None else abs

    def _close(self, actual, expected) -> bool:
        try:
            return math.isclose(actual, expected,
                                rel_tol=self.rel, abs_tol=self.abs)
        except TypeError:
            return actual == expected

    def __eq__(self, actual):
        if isinstance(self.expected, dict):
            if not isinstance(actual, dict) or set(actual) != set(self.expected):
                return False
            return all(self._close(actual[k], v)
                       for k, v in self.expected.items())
        if isinstance(self.expected, (list, tuple)):
            if not isinstance(actual, (list, tuple)) \
                    or len(actual) != len(self.expected):
                return False
            return all(self._close(a, e) for a, e in zip(actual, self.expected))
        return self._close(actual, self.expected)

    def __ne__(self, actual):
        return not self.__eq__(actual)

    def __repr__(self):
        return f"approx({self.expected!r})"


def approx(expected, rel=None, abs=None) -> Approx:  # noqa: A002 - pytest API
    return Approx(expected, rel=rel, abs=abs)
