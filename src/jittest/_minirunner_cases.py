"""Test-case collection and expansion for the mini-runner (roadmap P3-2).

mark.parametrize expansion, parametrized-fixture expansion, skip/skipif/xfail
marks, and collection of plain functions, Test* classes and unittest.TestCase
classes. Used by _minirunner; resolution lives in _fixtureengine.
"""
from __future__ import annotations

import inspect
import itertools
import unittest

from . import _pytestshim as shim
from ._fixtureengine import _call, _Fixture, _params_of
from ._pytestshim_core import PARAMETRIZE_ATTR


def _auto_id(value, index: int) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (str, int, float)):
        text = str(value)
        return text[:32] if text else str(index)
    return str(index)


def _param_values_id(entry, single: bool):
    """(value, id) from a shim param, a real pytest ParameterSet, or a raw
    value - duck-typed so either library's parametrize works here. A real
    ParameterSet always wraps the value in a tuple, so for a single argument
    name we unwrap the one-element tuple."""
    if isinstance(entry, shim.param):
        return entry.values, entry.id
    if hasattr(entry, "values") and hasattr(entry, "id"):
        values = entry.values
        pid = getattr(entry, "id", None)
        if single and isinstance(values, tuple) and len(values) == 1:
            values = values[0]
        return values, pid
    return entry, None


def _parametrize_layers(fn) -> list:
    """Parametrize layers from the shim's attribute and, when the candidate
    imported a real pytest, from real MarkDecorator objects in pytestmark."""
    layers = list(getattr(fn, PARAMETRIZE_ATTR, []))
    found = getattr(fn, shim.MARKS_ATTR, [])
    marks = found if isinstance(found, list) else [found]
    for m in marks:
        if getattr(m, "name", None) == "parametrize":
            args = getattr(m, "args", ())
            if len(args) >= 2:
                layers.append((args[0], list(args[1]),  # type: ignore[misc]
                               getattr(m, "kwargs", {}).get("ids")))
    return layers


def _parametrize_cases(fn) -> list[tuple[dict, list[str]]]:
    """Expand stacked @pytest.mark.parametrize layers into argument dicts."""
    cases: list[tuple[dict, list[str]]] = [({}, [])]
    for names, values, ids in _parametrize_layers(fn):
        # A ternary rather than an if/else assigning to the same name twice:
        # ruff SIM108, and it matches the shape already used in
        # _pytestshim_core.mark.parametrize.
        names = ([n.strip() for n in names.split(",")]
                 if isinstance(names, str) else list(names))
        single = len(names) == 1
        id_list = list(ids) if ids is not None else None
        expanded: list[tuple[dict, list[str]]] = []
        for i, entry in enumerate(values):
            raw, pid = _param_values_id(entry, single)
            values_tuple = (raw,) if single else tuple(raw)
            if id_list is not None and i < len(id_list) and id_list[i] is not None:
                pid = str(id_list[i])
            if pid is None:
                pid = _auto_id(raw, i)
            for argdict, id_parts in cases:
                merged = dict(argdict)
                # strict=False on purpose: a candidate whose parametrize row
                # does not match its argnames is the candidate's bug, and it
                # must surface as a test failure, not as a runner crash.
                for name, value in zip(names, values_tuple, strict=False):
                    merged[name] = value
                expanded.append((merged, [*id_parts, pid]))
        cases = expanded
    return cases


def _fixture_closure(requested: list[str], registry: dict[str, _Fixture],
                     seen: set | None = None) -> list[str]:
    """Every fixture name in the dependency closure, dependencies first."""
    seen = seen if seen is not None else set()
    ordered: list[str] = []
    for name in requested:
        if name in seen:
            continue
        seen.add(name)
        fixture = registry.get(name)
        if fixture is not None:
            for dep in _params_of(fixture.fn):
                if dep != "request":
                    ordered.extend(_fixture_closure([dep], registry, seen))
        ordered.append(name)
    return ordered


def _fixture_param_cases(closure: list[str], registry: dict[str, _Fixture],
                         argnames: set) -> list[tuple[dict, list[str]]]:
    """Parametrised fixtures in the closure expand the test into one case
    per value combination; overrides are keyed by fixture name."""
    choices: list[tuple[str, list[tuple[int, object, str]]]] = []
    for name in closure:
        if name in argnames:
            continue  # provided by parametrize, not by a fixture
        fixture = registry.get(name)
        if fixture is None or fixture.params is None:
            continue
        entries = []
        for i, entry in enumerate(fixture.params):
            value, pid = _param_values_id(entry, True)
            if pid is None and fixture.ids is not None \
                    and i < len(fixture.ids) and fixture.ids[i] is not None:
                pid = str(fixture.ids[i])
            entries.append((i, value, pid or _auto_id(value, i)))
        choices.append((name, entries))
    if not choices:
        return [({}, [])]
    cases: list[tuple[dict, list[str]]] = []
    names = [name for name, _ in choices]
    for combo in itertools.product(*[entries for _, entries in choices]):
        # product() yields one entry per choice, so the lengths always match.
        overrides = {name: (i, value)
                     for name, (i, value, _id) in zip(names, combo, strict=True)}
        ids = [_id for _i, _v, _id in combo]
        cases.append((overrides, ids))
    return cases


def _marks_of(*holders) -> list:
    marks: list = []
    for holder in holders:
        if holder is None:
            continue
        found = getattr(holder, shim.MARKS_ATTR, [])
        if isinstance(found, list):
            marks.extend(found)
        else:
            marks.append(found)
    return marks


def _skip_reason(marks: list) -> str | None:
    for m in marks:
        name = getattr(m, "name", None)
        if name == "skip":
            return getattr(m, "kwargs", {}).get("reason") or "skipped"
        if name == "skipif":
            args = getattr(m, "args", ())
            if args and args[0]:
                return getattr(m, "kwargs", {}).get("reason") or "skipif"
    return None


def _xfail_mark(marks: list):
    for m in marks:
        if getattr(m, "name", None) == "xfail":
            args = getattr(m, "args", ())
            if args and not args[0]:
                continue  # xfail(condition=False) means: run normally
            return m
    return None


class _Case:
    def __init__(self, label: str, run, requested: list[str], marks: list,
                 param_overrides: dict):
        self.label = label
        self.run = run  # callable(kwargs: dict) -> None
        self.requested = requested
        self.marks = marks
        self.param_overrides = param_overrides


def _has_own_init(cls) -> bool:
    return "__init__" in vars(cls)


def _make_function_case(name: str, fn, marks: list,
                        registry: dict[str, _Fixture],
                        autouse: list[str]) -> list[_Case]:
    p_cases = _parametrize_cases(fn)
    requested_all = _params_of(fn)
    cases: list[_Case] = []
    for argdict, id_parts in p_cases:
        inject = [p for p in requested_all if p not in argdict]
        # Autouse fixtures are resolved for their side effects but only
        # injected when the test actually declares them.
        requested = inject + [a for a in autouse if a not in inject]
        closure = _fixture_closure(requested, registry)
        for overrides, f_ids in _fixture_param_cases(closure, registry,
                                                     set(argdict)):
            ids = "-".join([*id_parts, *f_ids])
            label = f"{name}[{ids}]" if ids else name

            def run(kwargs, fn=fn, argdict=argdict, inject=inject):
                merged = {k: v for k, v in kwargs.items() if k in inject}
                merged.update(argdict)
                _call(lambda: fn(**merged))

            cases.append(_Case(label, run, requested, marks, overrides))
    return cases


def _make_method_cases(cls, class_marks: list,
                       registry: dict[str, _Fixture],
                       autouse: list[str]) -> list[_Case]:
    is_testcase = issubclass(cls, unittest.TestCase)
    cases: list[_Case] = []
    methods = [n for n, v in vars(cls).items()
               if n.startswith("test_") and callable(v)]
    for method_name in methods:
        method = getattr(cls, method_name)
        marks = [*_marks_of(cls), *class_marks, *_marks_of(method)]
        if is_testcase:
            def run_testcase(kwargs, cls=cls, method_name=method_name, argdict=None, inject=None):
                instance = cls(method_name)
                set_up = getattr(instance, "setUp", None)
                tear_down = getattr(instance, "tearDown", None)
                if set_up is not None:
                    _call(set_up)
                try:
                    _call(getattr(instance, method_name))
                finally:
                    if tear_down is not None:
                        _call(tear_down)

            cases.append(_Case(f"{cls.__name__}.{method_name}", run_testcase,
                               list(autouse), marks, {}))
            continue

        p_cases = _parametrize_cases(method)
        requested_all = [p for p in _params_of(method) if p != "self"]
        for argdict, id_parts in p_cases:
            inject = [p for p in requested_all if p not in argdict]
            requested = inject + [a for a in autouse if a not in inject]
            closure = _fixture_closure(requested, registry)
            for overrides, f_ids in _fixture_param_cases(closure, registry,
                                                         set(argdict)):
                ids = "-".join([*id_parts, *f_ids])
                label = (f"{cls.__name__}.{method_name}[{ids}]" if ids
                         else f"{cls.__name__}.{method_name}")

                def run_parametrized(kwargs, cls=cls, method_name=method_name, argdict=argdict,
                                     inject=inject):
                    instance = cls()
                    bound = getattr(instance, method_name)
                    set_up = getattr(instance, "setup_method", None)
                    tear_down = getattr(instance, "teardown_method", None)
                    if set_up is not None:
                        _call(lambda: set_up(bound))
                    try:
                        merged = {k: v for k, v in kwargs.items() if k in inject}
                        merged.update(argdict)
                        _call(lambda: bound(**merged))
                    finally:
                        if tear_down is not None:
                            _call(lambda: tear_down(bound))

                cases.append(_Case(label, run_parametrized, requested, marks, overrides))
    return cases


def _build_cases(module, registry: dict[str, _Fixture]) -> list[_Case]:
    module_marks = _marks_of(module)
    autouse = [name for name, f in registry.items() if f.autouse]
    cases: list[_Case] = []
    for name, obj in vars(module).items():
        if name.startswith("test_") and inspect.isfunction(obj):
            cases.extend(_make_function_case(name, obj,
                                             [*_marks_of(obj), *module_marks],
                                             registry, autouse))
        elif name.startswith("Test") and inspect.isclass(obj):
            if _has_own_init(obj):
                continue  # pytest does not collect classes with constructors
            cases.extend(_make_method_cases(obj, module_marks, registry, autouse))
    return cases
