"""Assertion and mutation helpers for the jittest pytest shim.

Candidates and conftest.py files import ``pytest`` for ``raises``, ``approx``,
``MonkeyPatch`` and the capture fixtures. This module provides them;
jittest._pytestshim re-exports them and installs itself as ``pytest`` when no
real pytest is importable.
"""
from __future__ import annotations

import importlib
import math
import os
import re
import sys
from collections.abc import MutableMapping
from typing import Any, NamedTuple

from ._pytestshim_core import Failed


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
            # Lengths are equal by the check above, so strict is free here.
            return all(self._close(a, e)
                       for a, e in zip(actual, self.expected, strict=True))
        return self._close(actual, self.expected)

    def __ne__(self, actual):
        return not self.__eq__(actual)

    def __repr__(self):
        return f"approx({self.expected!r})"


def approx(expected, rel=None, abs=None) -> Approx:  # noqa: A002 - pytest API
    return Approx(expected, rel=rel, abs=abs)


class MonkeyPatch:
    """Real-MonkeyPatch-shaped undoable mutation helper."""

    notset: Any = object()

    def __init__(self):
        self._undo: list[tuple[Any, Any, Any]] = []
        self._savesyspath: list[str] | None = None
        self._cwd: str | None = None

    def setattr(self, target, name=None, value=notset, raising: bool = True):
        if isinstance(target, str):
            # "pkg.mod.attr" string form: setattr("a.b.c", value).
            module_name, _, attr = target.rpartition(".")
            obj = importlib.import_module(module_name)
            value = name if value is MonkeyPatch.notset else value
            name = attr
        else:
            obj = target
            if value is MonkeyPatch.notset:
                raise TypeError("monkeypatch.setattr needs a value")
        old = getattr(obj, name, MonkeyPatch.notset)
        if raising and old is MonkeyPatch.notset:
            raise AttributeError(f"{obj!r} has no attribute {name!r}")
        self._undo.append((obj, name, old))
        setattr(obj, name, value)

    def delattr(self, target, name=None, raising: bool = True):
        if isinstance(target, str):
            module_name, _, attr = target.rpartition(".")
            obj = importlib.import_module(module_name)
            name = attr
        else:
            obj = target
        if not hasattr(obj, name):
            if raising:
                raise AttributeError(f"{obj!r} has no attribute {name!r}")
            return
        self._undo.append((obj, name, getattr(obj, name)))
        delattr(obj, name)

    def setitem(self, mapping: MutableMapping, key, value) -> None:
        self._undo.append((mapping, key, mapping.get(key, MonkeyPatch.notset)))
        mapping[key] = value

    def delitem(self, mapping: MutableMapping, key, raising: bool = True) -> None:
        if key not in mapping:
            if raising:
                raise KeyError(key)
            return
        self._undo.append((mapping, key, mapping[key]))
        del mapping[key]

    def setenv(self, name: str, value: str) -> None:
        self.setitem(os.environ, name, str(value))

    def delenv(self, name: str, raising: bool = True) -> None:
        self.delitem(os.environ, name, raising=raising)

    def syspath_prepend(self, path) -> None:
        if self._savesyspath is None:
            self._savesyspath = sys.path[:]
        sys.path.insert(0, str(path))

    def chdir(self, path) -> None:
        if self._cwd is None:
            self._cwd = os.getcwd()
        os.chdir(str(path))

    def undo(self) -> None:
        for obj, key, old in reversed(self._undo):
            if old is MonkeyPatch.notset:
                if isinstance(obj, MutableMapping):
                    obj.pop(key, None)
                elif hasattr(obj, key):
                    delattr(obj, key)
            elif isinstance(obj, MutableMapping):
                obj[key] = old
            else:
                setattr(obj, key, old)
        self._undo.clear()
        if self._savesyspath is not None:
            sys.path[:] = self._savesyspath
            self._savesyspath = None
        if self._cwd is not None:
            os.chdir(self._cwd)
            self._cwd = None


class CaptureResult(NamedTuple):
    out: str
    err: str


class _NoCapture:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class CaptureFixture:
    """capsys: sys-level capture. readouterr() returns and drains."""

    def __init__(self):
        import io
        self._out = io.StringIO()
        self._err = io.StringIO()
        self._saved: tuple | None = None

    def start(self):
        self._saved = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self._out, self._err

    def stop(self):
        if self._saved is not None:
            sys.stdout, sys.stderr = self._saved
            self._saved = None

    def readouterr(self) -> CaptureResult:
        result = CaptureResult(self._out.getvalue(), self._err.getvalue())
        self._out.seek(0)
        self._out.truncate(0)
        self._err.seek(0)
        self._err.truncate(0)
        return result

    def disabled(self) -> _NoCapture:
        self.stop()
        return _NoCapture()
