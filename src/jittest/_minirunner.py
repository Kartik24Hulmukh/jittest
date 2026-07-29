"""A small test runner, used only when pytest is not importable.

Why this exists: jittest must be able to answer the question "does this test
pass here?" in environments where we cannot install anything - hardened CI
images, air-gapped runners, or a first-time user who has not created a virtual
environment yet. Refusing to run is a worse answer than running a smaller
runner.

Exit codes deliberately mirror pytest so the oracle needs no special cases:

    0  at least one test executed and every executed test passed
    1  at least one test failed (fixture errors count: loud, never silent)
    2  the file could not be imported or collected
    5  nothing executed: no tests collected, or every collected test skipped

Exit 0 deliberately requires a test to have ACTUALLY RUN. Returning 0 after
skipping everything is what let the differential oracle conclude "passes on
base" about code it never executed (Defect 32).

Fixtures (roadmap P3-2). A candidate test in a pytest-native repository almost
always does ``import pytest`` and uses fixtures from the repo's conftest.py.
Before this support existed, such candidates either died at collection
(import error) or were silently skipped, and jittest caught nothing while
saying nothing. The mini-runner installs jittest._pytestshim as ``pytest`` for
the duration of the run (restoring any real pytest afterwards), loads
conftest.py (nearest definitions win, then the test module), and resolves
fixtures recursively - cycle detection, function/module scopes, yield
teardown, autouse, parametrized fixtures, request.param, mark.parametrize,
skip/skipif/xfail, and the built-ins tmp_path, tmp_path_factory, monkeypatch,
capsys. Resolution lives in _fixtureengine; collection in _minirunner_cases.

Deliberately unsupported (fail loudly, never silently pass): async fixtures,
doctest, capfd, pytest.ini options, plugin hooks, and unittest addCleanup.
"""
from __future__ import annotations

import importlib.util
import sys
import traceback
import unittest
from pathlib import Path

from . import _pytestshim as shim
from ._fixtureengine import (
    _FixtureLookupError,
    _FixtureState,
    _builtin_fixtures,
    _conftest_paths,
    _fixtures_from,
)
from ._minirunner_cases import _build_cases, _skip_reason, _xfail_mark

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_COLLECTION_ERROR = 2
EXIT_NO_TESTS = 5


def _load(path: Path, module_name: str | None = None):
    name = module_name or path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE exec: a partially-executed module must be findable, and
    # dataclasses inside the module resolve their own module by name.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_file(path: Path) -> int:
    """Run one test file under the shim, restoring any real pytest after.

    The shim is installed for the duration of the run so the candidate gets
    its deterministic surface; a real pytest that was already installed is put
    back afterwards, so calling run_file from inside a pytest session does not
    pollute the surrounding installation.
    """
    sentinel = object()
    previous = sys.modules.get("pytest", sentinel)
    shim.install()
    try:
        return _run_file(path)
    finally:
        if previous is sentinel:
            sys.modules.pop("pytest", None)
        else:
            sys.modules["pytest"] = previous


def _run_file(path: Path) -> int:
    try:
        module = _load(path)
    except BaseException:
        print(f"COLLECTION ERROR in {path.name}", file=sys.stderr)
        traceback.print_exc()
        return EXIT_COLLECTION_ERROR

    registry = _builtin_fixtures()
    conftests = _conftest_paths(path.resolve().parent, Path.cwd())
    for conf in reversed(conftests):  # reversed: nearest conftest wins
        try:
            conf_module = _load(
                conf, f"jittest_conftest_{abs(hash(str(conf))) & 0xffffffff:x}")
        except BaseException:
            print(f"COLLECTION ERROR in {conf}", file=sys.stderr)
            traceback.print_exc()
            return EXIT_COLLECTION_ERROR
        registry.update(_fixtures_from(conf_module))
    registry.update(_fixtures_from(module))  # the test module wins over conftest

    cases = _build_cases(module, registry)
    if not cases:
        print("no tests collected", file=sys.stderr)
        return EXIT_NO_TESTS

    state = _FixtureState()
    failures = 0
    executed = 0
    for case in cases:
        reason = _skip_reason(case.marks)
        if reason is not None:
            print(f"SKIP {case.label}: {reason}", file=sys.stderr)
            continue
        xfail = _xfail_mark(case.marks)
        try:
            kwargs = {name: state.resolve(name, registry, case.param_overrides)
                      for name in case.requested}
            if xfail is not None:
                try:
                    case.run(kwargs)
                except Exception as exc:
                    print(f"XFAIL {case.label}: {exc}", file=sys.stderr)
                else:
                    strict = getattr(xfail, "kwargs", {}).get("strict", False)
                    if strict:
                        executed += 1
                        failures += 1
                        print(f"FAIL {case.label}: XPASS(strict)", file=sys.stderr)
                    else:
                        executed += 1
                        print(f"XPASS {case.label}")
            else:
                case.run(kwargs)
                executed += 1
                print(f"PASS {case.label}")
        except unittest.SkipTest as exc:
            print(f"SKIP {case.label}: {exc}", file=sys.stderr)
        except _FixtureLookupError as exc:
            failures += 1
            print(f"ERROR {case.label}: {exc}", file=sys.stderr)
        except BaseException as exc:
            executed += 1
            failures += 1
            print(f"FAIL {case.label}: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
        finally:
            try:
                state.finish_function()
            except BaseException as exc:
                failures += 1
                print(f"ERROR {case.label} teardown: {exc}", file=sys.stderr)
    state.finish_module()

    if failures:
        return EXIT_FAILED
    if executed == 0:
        print("no tests executed (every collected test was skipped)",
              file=sys.stderr)
        return EXIT_NO_TESTS
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(a) for a in args if not a.startswith("-")]
    if not paths:
        print("usage: python -m jittest._minirunner <test_file.py>", file=sys.stderr)
        return EXIT_COLLECTION_ERROR

    worst = EXIT_NO_TESTS
    for path in paths:
        code = run_file(path)
        if code == EXIT_COLLECTION_ERROR:
            return code
        if code == EXIT_FAILED:
            worst = EXIT_FAILED
        elif code == EXIT_OK and worst != EXIT_FAILED:
            worst = EXIT_OK
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
