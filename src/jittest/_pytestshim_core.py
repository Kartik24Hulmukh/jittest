"""Core fixture and mark machinery for the jittest pytest shim.

Candidates and conftest.py files import ``pytest`` for ``fixture``, ``mark``,
``skip``, ``fail``, ``xfail``, ``importorskip``, ``param`` and
``FixtureRequest``. This module provides them; jittest._pytestshim re-exports
them and installs itself as ``pytest`` when no real pytest is importable.
"""
from __future__ import annotations

import importlib
import unittest
from typing import Any, NamedTuple

FIXTURE_MARKER = "__jittest_fixture__"
MARKS_ATTR = "pytestmark"
PARAMETRIZE_ATTR = "__jittest_parametrize__"


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


class FixtureDef:
    """The record the runner reads to resolve one fixture."""

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
    """Usable as @fixture and @fixture(...). Marks the function with our own
    attribute AND the attribute real pytest uses."""
    def wrap(fn):
        fdef = FixtureDef(fn, scope=scope, params=params, autouse=autouse,
                          name=name, ids=ids)
        setattr(fn, FIXTURE_MARKER, fdef)
        fn._pytestfixturefunction = fdef
        return fn

    if callable(arg):
        return wrap(arg)
    return wrap


class param(NamedTuple):
    """pytest.param(value, id=...) for fixture params and parametrize."""
    values: Any
    id: str | None = None


class FixtureRequest:
    """The object passed to fixtures that ask for ``request``."""

    def __init__(self, fixturename: str, scope: str = "function",
                 has_param: bool = False, param_value=None):
        self.fixturename = fixturename
        self.scope = scope
        self._finalizers: list = []
        if has_param:
            self.param = param_value

    def addfinalizer(self, fn) -> None:
        self._finalizers.append(fn)


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
            existing = list(getattr(fn, PARAMETRIZE_ATTR, []))
            existing.append((names, list(argvalues), id_list))
            setattr(fn, PARAMETRIZE_ATTR, existing)
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
