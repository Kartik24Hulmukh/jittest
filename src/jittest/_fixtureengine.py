"""Fixture resolution machinery for the mini-runner (roadmap P3-2).

conftest.py loading, the fixture registry, recursive resolution with cycle
detection, function/module scopes, yield-fixture teardown, and the built-ins
tmp_path / tmp_path_factory / monkeypatch / capsys. Used by _minirunner.
"""
from __future__ import annotations

import asyncio
import inspect
import tempfile
import traceback
from pathlib import Path

from . import _pytestshim as shim


def _call(fn) -> None:
    if inspect.iscoroutinefunction(fn):
        asyncio.run(fn())
    else:
        fn()


def _conftest_paths(start: Path, stop: Path) -> list[Path]:
    """conftest.py files from the candidate's directory up to the cwd,
    nearest first, mirroring pytest's upwards walk bounded at the rootdir."""
    found: list[Path] = []
    directory = start.resolve()
    stop = stop.resolve()
    while True:
        candidate = directory / "conftest.py"
        if candidate.is_file():
            found.append(candidate)
        if directory == stop or directory.parent == directory:
            break
        directory = directory.parent
    return found


class _Fixture:
    """One fixture definition, normalised from either marking convention."""

    def __init__(self, name: str, fn, scope: str, params, autouse: bool,
                 ids=None):
        self.name = name
        self.fn = fn
        self.scope = scope if scope in ("function", "class", "module",
                                        "package", "session") else "function"
        self.params = list(params) if params is not None else None
        self.autouse = autouse
        self.ids = list(ids) if ids is not None else None

    @classmethod
    def from_marker(cls, fallback_name: str, fn, marker) -> _Fixture:
        scope = str(getattr(marker, "scope", "function") or "function")
        params = getattr(marker, "params", None)
        autouse = bool(getattr(marker, "autouse", False))
        name = getattr(marker, "name", None) or fallback_name
        return cls(name, fn, scope, params, autouse,
                   ids=getattr(marker, "ids", None))


def _unwrap_fixture(obj):
    """Real pytest's @pytest.fixture returns a FixtureFunctionDefinition that
    is not callable; recover the underlying function from it."""
    if callable(obj):
        return obj
    for attr in ("func", "_fixture_function", "__wrapped__"):
        target = getattr(obj, attr, None)
        if callable(target):
            return target
    getter = getattr(obj, "_get_wrapped_function", None)
    if callable(getter):
        try:
            target = getter()
        except Exception:
            return None
        if callable(target):
            return target
    return None


def _fixture_marker_of(obj):
    """The fixture marker from either the shim or a real pytest decorator."""
    marker = getattr(obj, shim.FIXTURE_MARKER, None)
    if marker is None:
        marker = getattr(obj, "_pytestfixturefunction", None)
    if marker is None:
        marker = getattr(obj, "_fixture_function_marker", None)
    return marker


def _fixtures_from(module) -> dict[str, _Fixture]:
    """Fixture definitions in one module, keyed by fixture name."""
    registry: dict[str, _Fixture] = {}
    for attr_name, obj in vars(module).items():
        marker = _fixture_marker_of(obj)
        if marker is None:
            continue
        target = _unwrap_fixture(obj)
        if target is None:
            continue
        fixture = _Fixture.from_marker(attr_name, target, marker)
        registry[fixture.name] = fixture
    return registry


class _TmpPathFactory:
    def __init__(self):
        self._base = Path(tempfile.mkdtemp(prefix="jittest-tmpf-"))
        self._n = 0

    def mktemp(self, basename: str, numbered: bool = True) -> Path:
        self._n += 1
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in basename)
        path = self._base / (f"{safe}{self._n}" if numbered else safe)
        path.mkdir(parents=True, exist_ok=True)
        return path


def _builtin_fixtures() -> dict[str, _Fixture]:
    def tmp_path():
        return Path(tempfile.mkdtemp(prefix="jittest-tmp-"))

    def tmp_path_factory():
        return _TmpPathFactory()

    def monkeypatch():
        mp = shim.MonkeyPatch()
        yield mp
        mp.undo()

    def capsys():
        cap = shim.CaptureFixture()
        cap.start()
        yield cap
        cap.stop()

    return {
        "tmp_path": _Fixture("tmp_path", tmp_path, "function", None, False),
        "tmp_path_factory": _Fixture(
            "tmp_path_factory", tmp_path_factory, "module", None, False),
        "monkeypatch": _Fixture("monkeypatch", monkeypatch, "function", None, False),
        "capsys": _Fixture("capsys", capsys, "function", None, False),
    }


class _FixtureLookupError(Exception):
    pass


class _FixtureState:
    """Cache and teardown bookkeeping for one run of one file."""

    def __init__(self):
        self._values: dict[tuple, object] = {}
        self._function_finalizers: list = []
        self._module_finalizers: list = []

    @staticmethod
    def _bucket(scope: str) -> str:
        return "function" if scope == "function" else "module"

    def resolve(self, name: str, registry: dict[str, _Fixture],
                param_overrides: dict, stack: tuple = ()):
        key = (self._bucket_for(name, registry), name,
               (param_overrides or {}).get(name))
        if key in self._values:
            return self._values[key]
        return self._create(name, registry, param_overrides, stack, key)

    def _bucket_for(self, name: str, registry: dict[str, _Fixture]) -> str:
        fixture = registry.get(name)
        return self._bucket(fixture.scope) if fixture else "function"

    def _create(self, name: str, registry: dict[str, _Fixture],
                param_overrides: dict, stack: tuple, key):
        if name in stack:
            raise _FixtureLookupError(
                f"circular fixture dependency: {' -> '.join((*stack, name))}")
        fixture = registry.get(name)
        if fixture is None:
            raise _FixtureLookupError(
                f"fixture '{name}' not found (checked conftest.py, the test "
                f"module, and built-ins tmp_path/monkeypatch/capsys)")
        deps: dict = {}
        for dep in _params_of(fixture.fn):
            if dep == "request":
                override = (param_overrides or {}).get(name)
                has_param = fixture.params is not None and override is not None
                deps[dep] = shim.FixtureRequest(
                    fixturename=name, scope=fixture.scope,
                    has_param=has_param,
                    param_value=override[1] if has_param else None)
                continue
            deps[dep] = self.resolve(dep, registry, param_overrides,
                                     (*stack, name))
        if inspect.isasyncgenfunction(fixture.fn) or inspect.iscoroutinefunction(
                fixture.fn):
            raise _FixtureLookupError(
                f"async fixture '{name}' is not supported by the mini-runner; "
                f"install pytest")
        if inspect.isgeneratorfunction(fixture.fn):
            gen = fixture.fn(**deps)
            value = next(gen)
            request = deps.get("request")

            def finalize(gen=gen, request=request):
                if request is not None:
                    for fin in reversed(request._finalizers):
                        fin()
                    request._finalizers.clear()
                try:
                    next(gen)
                except StopIteration:
                    return
                raise RuntimeError(
                    f"yield fixture '{name}' yielded more than once")
        else:
            value = fixture.fn(**deps)
            request = deps.get("request")

            def finalize(request=request):
                if request is not None:
                    for fin in reversed(request._finalizers):
                        fin()
                    request._finalizers.clear()

        self._values[key] = value
        if self._bucket(fixture.scope) == "function":
            self._function_finalizers.append(finalize)
        else:
            self._module_finalizers.append(finalize)
        return value

    def finish_function(self) -> None:
        errors = []
        for finalize in reversed(self._function_finalizers):
            try:
                finalize()
            except Exception as exc:  # teardown errors are loud, not silent
                errors.append(exc)
        self._function_finalizers.clear()
        if errors:
            raise errors[0]

    def finish_module(self) -> None:
        for finalize in reversed(self._module_finalizers):
            try:
                finalize()
            except Exception:
                traceback.print_exc()
        self._module_finalizers.clear()


def _params_of(fn) -> list[str]:
    try:
        return [p for p in inspect.signature(fn).parameters
                if p not in ("self", "cls")]
    except (TypeError, ValueError):
        return []
