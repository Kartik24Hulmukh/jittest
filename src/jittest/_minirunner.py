"""A small test runner, used only when pytest is not importable.

Why this exists: jittest must be able to answer the question "does this test
pass here?" in environments where we cannot install anything - hardened CI
images, air-gapped runners, or a first-time user who has not created a virtual
environment yet. Refusing to run is a worse answer than running a smaller
runner.

Exit codes deliberately mirror pytest so the oracle needs no special cases:

    0  at least one test executed and every executed test passed
    1  at least one test failed
    2  the file could not be imported or collected
    5  nothing executed: no tests collected, or every collected test skipped

Exit 0 deliberately requires a test to have ACTUALLY RUN. Returning 0 after
skipping everything is what let the differential oracle conclude "passes on
base" about code it never executed (Defect 32).

Fixtures (P3-2): the runner implements a deliberately small, explicitly named
subset of pytest's built-in fixtures - tmp_path, monkeypatch and capsys -
because those are the fixtures model-generated candidate tests actually use.
A test requesting any other fixture is SKIPPED with the fixture named, and a
skip is never a pass. This subset is what converts the most common "silently
skipped" candidates into tests that really execute.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import io
import json
import os
import sys
import tempfile
import traceback
import unittest
from pathlib import Path
from types import SimpleNamespace

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_COLLECTION_ERROR = 2
EXIT_NO_TESTS = 5

_UNSET = object()


class _UnknownFixture(Exception):
    """A test asked for a fixture the mini-runner does not implement."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


class _MonkeyPatch:
    """Minimal subset of pytest's monkeypatch: the methods generated tests use.

    Every mutation is recorded and reversed by undo(), so a candidate cannot
    leak state into the runner process or into the next test.
    """

    def __init__(self) -> None:
        self._undo: list = []

    def setattr(self, target, name, value=_UNSET) -> None:
        if value is _UNSET and isinstance(target, str):
            # Dotted form: monkeypatch.setattr("module.attr", value)
            value = name
            module_path, _, attr = target.rpartition(".")
            obj = importlib.import_module(module_path)
        else:
            obj, attr = target, name
        old = getattr(obj, attr, _UNSET)
        if old is _UNSET:
            self._undo.append(lambda: delattr(obj, attr))
        else:
            self._undo.append(lambda: setattr(obj, attr, old))
        setattr(obj, attr, value)

    def delattr(self, target, name=None, raising=True) -> None:
        if name is None:
            module_path, _, attr = target.rpartition(".")
            obj = importlib.import_module(module_path)
        else:
            obj, attr = target, name
        old = getattr(obj, attr, _UNSET)
        if old is _UNSET:
            if raising:
                raise AttributeError(attr)
            return
        self._undo.append(lambda: setattr(obj, attr, old))
        delattr(obj, attr)

    def setitem(self, mapping, name, value) -> None:
        old = mapping.get(name, _UNSET)
        if old is _UNSET:
            self._undo.append(lambda: mapping.__delitem__(name))
        else:
            self._undo.append(lambda: mapping.__setitem__(name, old))
        mapping[name] = value

    def delitem(self, mapping, name, raising=True) -> None:
        if name not in mapping:
            if raising:
                raise KeyError(name)
            return
        old = mapping[name]
        self._undo.append(lambda: mapping.__setitem__(name, old))
        del mapping[name]

    def setenv(self, name, value) -> None:
        self.setitem(os.environ, name, str(value))

    def delenv(self, name, raising=True) -> None:
        self.delitem(os.environ, name, raising=raising)

    def syspath_prepend(self, path) -> None:
        self._undo.append(lambda: sys.path.remove(str(path)))
        sys.path.insert(0, str(path))

    def undo(self) -> None:
        for undo in reversed(self._undo):
            try:
                undo()
            except Exception:
                pass
        self._undo.clear()


class _Capsys:
    """Minimal capsys: sys-level capture with readouterr()."""

    def __init__(self) -> None:
        self._out = io.StringIO()
        self._err = io.StringIO()
        self._prev = None

    def install(self) -> None:
        self._prev = (sys.stdout, sys.stderr)
        sys.stdout, sys.stderr = self._out, self._err

    def restore(self) -> None:
        if self._prev is not None:
            sys.stdout, sys.stderr = self._prev
            self._prev = None

    def readouterr(self):
        out, err = self._out.getvalue(), self._err.getvalue()
        self._out.seek(0)
        self._out.truncate(0)
        self._err.seek(0)
        self._err.truncate(0)
        return SimpleNamespace(out=out, err=err)


def _run_cleanups(cleanups: list) -> None:
    for cleanup in reversed(cleanups):
        try:
            cleanup()
        except Exception:
            pass


def _build_fixtures(sig: inspect.Signature) -> tuple[dict, list]:
    """Resolve a callable's parameters to mini-runner fixtures.

    Returns (kwargs, cleanups). Raises _UnknownFixture for any parameter the
    runner does not implement; already-created fixtures are cleaned up before
    re-raising so a half-built set never leaks a redirect or a mutation.
    """
    kwargs: dict = {}
    cleanups: list = []
    try:
        for name in sig.parameters:
            if name == "tmp_path":
                tmp = tempfile.TemporaryDirectory(prefix="jittest-tmp-")
                cleanups.append(tmp.cleanup)
                kwargs[name] = Path(tmp.name)
            elif name == "monkeypatch":
                patch = _MonkeyPatch()
                cleanups.append(patch.undo)
                kwargs[name] = patch
            elif name == "capsys":
                cap = _Capsys()
                cap.install()
                cleanups.append(cap.restore)
                kwargs[name] = cap
            else:
                raise _UnknownFixture(name)
    except BaseException:
        _run_cleanups(cleanups)
        raise
    return kwargs, cleanups


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _call(fn, kwargs: dict | None = None) -> None:
    kwargs = kwargs or {}
    if inspect.iscoroutinefunction(fn):
        asyncio.run(fn(**kwargs))
    else:
        fn(**kwargs)


def _collect(module) -> list[tuple[str, object]]:
    tests: list[tuple[str, object]] = []
    for name in dir(module):
        obj = getattr(module, name)
        if name.startswith("test_") and callable(obj):
            tests.append((name, obj))
        elif name.startswith("Test") and inspect.isclass(obj):
            for method_name in dir(obj):
                if method_name.startswith("test_"):
                    tests.append((f"{name}.{method_name}", (obj, method_name)))
    return tests


def _execute_tests(tests: list[tuple[str, object]]) -> tuple[int, list[dict]]:
    failures = 0
    executed = 0
    cases: list[dict] = []
    for label, target in tests:
        try:
            if isinstance(target, tuple):
                cls, method_name = target
                instance = cls()
                method = getattr(instance, method_name)
                kwargs, cleanups = _build_fixtures(inspect.signature(method))
                try:
                    if hasattr(instance, "setup_method"):
                        instance.setup_method(method)
                    _call(method, kwargs)
                    if hasattr(instance, "teardown_method"):
                        instance.teardown_method(method)
                finally:
                    _run_cleanups(cleanups)
            else:
                kwargs, cleanups = _build_fixtures(inspect.signature(target))
                try:
                    _call(target, kwargs)
                finally:
                    _run_cleanups(cleanups)
            executed += 1
            print(f"PASS {label}")
            cases.append({"label": label, "outcome": "pass"})
        except _UnknownFixture as exc:
            # An unimplemented fixture asserted nothing. Name it in the skip.
            print(f"SKIP {label}: fixture '{exc.name}' is not implemented by "
                  "the mini-runner; install pytest", file=sys.stderr)
            cases.append({"label": label, "outcome": "skip"})
        except unittest.SkipTest as exc:
            # A skipped test asserted nothing. It must not count as a pass.
            print(f"SKIP {label}: {exc}", file=sys.stderr)
            cases.append({"label": label, "outcome": "skip"})
        except BaseException as exc:
            executed += 1
            failures += 1
            print(f"FAIL {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            cases.append({"label": label, "outcome": "fail"})

    if failures:
        return EXIT_FAILED, cases
    if executed == 0:
        print("no tests executed (every collected test was skipped)",
              file=sys.stderr)
        return EXIT_NO_TESTS, cases
    return EXIT_OK, cases


def _run(path: Path) -> tuple[int, list[dict]]:
    try:
        module = _load(path)
    except BaseException:
        print(f"COLLECTION ERROR in {path.name}", file=sys.stderr)
        traceback.print_exc()
        return EXIT_COLLECTION_ERROR, []

    tests = _collect(module)
    if not tests:
        print("no tests collected", file=sys.stderr)
        return EXIT_NO_TESTS, []
    return _execute_tests(tests)


def run_file(path: Path) -> int:
    return _run(path)[0]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    report_json: str | None = None
    paths: list[Path] = []
    for arg in args:
        if arg.startswith("--report-json="):
            report_json = arg.split("=", 1)[1]
        elif not arg.startswith("-"):
            paths.append(Path(arg))
    if not paths:
        print("usage: python -m jittest._minirunner <test_file.py> "
              "[--report-json=PATH]", file=sys.stderr)
        return EXIT_COLLECTION_ERROR

    worst = EXIT_NO_TESTS
    all_cases: list[dict] = []
    for path in paths:
        code, cases = _run(path)
        all_cases.extend(cases)
        if code == EXIT_COLLECTION_ERROR:
            return code
        if code == EXIT_FAILED:
            worst = EXIT_FAILED
        elif code == EXIT_OK and worst != EXIT_FAILED:
            worst = EXIT_OK
    if report_json:
        # The per-test channel the oracle compares against (Defect 32b).
        try:
            Path(report_json).write_text(
                json.dumps({"cases": all_cases}), encoding="utf-8")
        except OSError:
            pass
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
