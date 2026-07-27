"""A ~100 line test runner, used only when pytest is not importable.

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
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import sys
import traceback
import unittest
from pathlib import Path

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_COLLECTION_ERROR = 2
EXIT_NO_TESTS = 5


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


def _call(fn) -> None:
    if inspect.iscoroutinefunction(fn):
        asyncio.run(fn())
    else:
        fn()


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


def run_file(path: Path) -> int:
    try:
        module = _load(path)
    except BaseException:
        print(f"COLLECTION ERROR in {path.name}", file=sys.stderr)
        traceback.print_exc()
        return EXIT_COLLECTION_ERROR

    tests = _collect(module)
    if not tests:
        print("no tests collected", file=sys.stderr)
        return EXIT_NO_TESTS

    failures = 0
    executed = 0
    for label, target in tests:
        try:
            if isinstance(target, tuple):
                cls, method_name = target
                instance = cls()
                if hasattr(instance, "setup_method"):
                    instance.setup_method(getattr(instance, method_name))
                _call(getattr(instance, method_name))
                if hasattr(instance, "teardown_method"):
                    instance.teardown_method(getattr(instance, method_name))
            else:
                sig = inspect.signature(target)
                if sig.parameters:
                    print(f"SKIP {label}: fixtures are not supported by the "
                          "mini-runner; install pytest", file=sys.stderr)
                    continue
                _call(target)
            executed += 1
            print(f"PASS {label}")
        except unittest.SkipTest as exc:
            # A skipped test asserted nothing. It must not count as a pass.
            print(f"SKIP {label}: {exc}", file=sys.stderr)
        except BaseException as exc:
            executed += 1
            failures += 1
            print(f"FAIL {label}: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()

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
