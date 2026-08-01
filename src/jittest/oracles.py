"""Oracle-strength scanning for test code.

This module exists because of a paper. arXiv 2606.18168, "All Smoke, No Alarm:
Oracle Signals in Agent-Authored Test Code" (Banik, Chowdhury and Shamim,
16 June 2026), classified 86,156 cumulative test-file patches drawn from 33,596
agent-authored pull requests across 2,807 repositories and found that 80.2% of
them carry a weak oracle or no oracle at all: a test that executes code and
then asserts nothing meaningful about the result. The same study reports that a
strong oracle remains a significant predictor of the pull request being merged
after adjusting for agent, patch size, stars, task type and language (adjusted
odds ratio 1.28, p < 0.001), and it closes by recommending "oracle-aware CI
checks that flag newly added test files lacking assertion patterns".

This module is that check.

Every design constraint here is deliberate:

* Standard library only, like the rest of jittest. No new dependency lands in
  somebody else's locked project because of us.
* No model call, no network, no API key, no dollar cost.
* Deterministic. The same bytes always produce the same verdict, so this can
  gate CI without the completion-rate, rate-limit and pricing problems that
  make the catching-test pipeline expensive to measure.
* No source code ever leaves this module. A finding carries a category, a
  symbol name and a line number, never the body of the test. jittest asserts
  that property of its telemetry in ``test_telemetry_never_contains_source_code``
  and there is no reason to hold a second reporting path to a lower standard.
  This is also why a syntax error is reported by exception type only:
  ``SyntaxError.text`` contains the offending source line.

The taxonomy is the paper's, reproduced here so that a verdict is auditable
against the source it came from:

====  ==================================  ==========================================
Code  Meaning                             Example
====  ==================================  ==========================================
W1    no assertion at all                 ``result = f()``
W2    existence or null check only        ``assert result``, ``assertIsNotNone(x)``
W3    boolean-only                        ``assertTrue(f())``, ``assert x is True``
W4    mock verification only              ``m.assert_called_once_with(3)``
W5    snapshot comparison only            ``assert page == snapshot``
S1    value equality or ordering          ``assert f(2) == 4``, ``assertIn(a, b)``
S2    error containment or type           ``pytest.raises``, ``assertIsInstance``
S3    two or more strong signals          both of the above in one test
====  ==================================  ==========================================

A test is *strong* when its verdict starts with S. Everything else is smoke.

The scanner reports. It does not rewrite anyone's tests, and it does not claim
that a weak oracle is a bug: a smoke test is a legitimate thing to write on
purpose. What it claims is narrower and defensible - that a reviewer should be
told, before merging, that the new test file added in this pull request asserts
nothing about the value under test.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .diff import (
    GitError,
    git_diff,
    git_show,
    is_probably_test_file,
    is_safe_repo_path,
    parse_unified_diff,
)

__all__ = [
    "CATEGORIES", "CATEGORY_LABELS", "STRONG_CATEGORIES", "WEAK_CATEGORIES",
    "FileOracles", "OracleReport", "OracleScanError", "TestOracle",
    "scan_changed", "scan_paths", "scan_source", "to_markdown", "to_terminal",
]

WEAK_CATEGORIES = ("W1", "W2", "W3", "W4", "W5")
STRONG_CATEGORIES = ("S1", "S2", "S3")
CATEGORIES = WEAK_CATEGORIES + STRONG_CATEGORIES

CATEGORY_LABELS = {
    "W1": "no assertion",
    "W2": "existence or null check only",
    "W3": "boolean-only assertion",
    "W4": "mock verification only",
    "W5": "snapshot comparison only",
    "S1": "value equality or ordering",
    "S2": "error containment or type",
    "S3": "two or more strong signals",
}


class OracleScanError(RuntimeError):
    """The scan could not be performed.

    Deliberately distinct from a scan that ran and found no test files. The
    first is the absence of a fact; the second is a fact. Conflating the two is
    the mistake that produced Defect 22 on this project and it is not repeated
    here.
    """


# ---------------------------------------------------------------------------
# Signal vocabulary
# ---------------------------------------------------------------------------

_EQUALITY_METHODS = frozenset({
    "assertEqual", "assertNotEqual", "assertEquals", "assertAlmostEqual",
    "assertNotAlmostEqual", "assertListEqual", "assertDictEqual",
    "assertSetEqual", "assertTupleEqual", "assertMultiLineEqual",
    "assertCountEqual", "assertSequenceEqual", "assertIn", "assertNotIn",
    "assertGreater", "assertGreaterEqual", "assertLess", "assertLessEqual",
    "assertRegex", "assertNotRegex", "assert_array_equal",
    "assert_array_almost_equal", "assert_allclose", "assert_frame_equal",
    "assert_series_equal", "assert_index_equal",
})

_ERROR_METHODS = frozenset({
    "assertRaises", "assertRaisesRegex", "assertRaisesRegexp", "assertWarns",
    "assertWarnsRegex", "assertLogs", "assertNoLogs",
})

_TYPE_METHODS = frozenset({"assertIsInstance", "assertNotIsInstance"})
_BOOLEAN_METHODS = frozenset({"assertTrue", "assertFalse"})
_NULL_METHODS = frozenset({"assertIsNone", "assertIsNotNone", "assertIs",
                           "assertIsNot"})
_SNAPSHOT_METHODS = frozenset({
    "toMatchSnapshot", "assert_match", "assert_snapshot",
    "assert_match_snapshot", "check",
})
_SNAPSHOT_NAMES = frozenset({
    "snapshot", "snapshot_json", "file_regression", "data_regression",
    "num_regression", "ndarrays_regression", "image_regression",
})
_MOCK_PREFIXES = (
    "assert_called", "assert_any_call", "assert_has_calls",
    "assert_not_called", "assert_awaited", "assert_not_awaited",
)
# `pytest.raises` and `pytest.warns` are the two context managers that carry a
# real oracle. Matched on the dotted root as well as the leaf, because a bare
# `raises(...)` is far more likely to be a helper of the project's own than a
# pytest import, and guessing wrong in the generous direction would inflate the
# strong-oracle rate, which is the one number this module must not overstate.
_PYTEST_ROOTS = frozenset({"pytest", "py", "_pytest"})
_PYTEST_ERROR_LEAVES = frozenset({"raises", "warns", "deprecated_call"})

_ORDERING_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)


def _dotted(node: ast.AST) -> str:
    """`self.assertEqual` / `pytest.raises` / `m.assert_called_once_with`."""
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif isinstance(current, ast.Call):
        parts.append("()")
    return ".".join(reversed(parts))


def _mentions_snapshot(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and child.id in _SNAPSHOT_NAMES:
            return True
        if isinstance(child, ast.Attribute) and child.attr in _SNAPSHOT_NAMES:
            return True
    return False


def _signal_for_call(call: ast.Call) -> str | None:
    """The oracle signal a call expression carries, or None if it carries none.

    None is the common case and it is the important one: a call that is not an
    assertion is just an action, and a test made only of actions is W1.
    """
    dotted = _dotted(call.func)
    if not dotted:
        return None
    parts = dotted.split(".")
    leaf = parts[-1]
    root = parts[0]

    if leaf in _EQUALITY_METHODS:
        return "S1"
    if leaf in _ERROR_METHODS or leaf in _TYPE_METHODS:
        return "S2"
    if leaf in _PYTEST_ERROR_LEAVES and root in _PYTEST_ROOTS:
        return "S2"
    if leaf in _BOOLEAN_METHODS:
        return "W3"
    if leaf in _NULL_METHODS:
        return "W2"
    if leaf in _SNAPSHOT_METHODS and _mentions_snapshot(call):
        return "W5"
    if leaf == "toMatchSnapshot":
        return "W5"
    if any(leaf.startswith(prefix) for prefix in _MOCK_PREFIXES):
        return "W4"
    return None


def _signal_for_compare(node: ast.Compare) -> str:
    if _mentions_snapshot(node):
        return "W5"
    for op, comparator in zip(node.ops, node.comparators, strict=False):
        constant = comparator if isinstance(comparator, ast.Constant) else None
        if isinstance(op, (ast.Is, ast.IsNot)):
            if constant is not None and isinstance(constant.value, bool):
                return "W3"
            return "W2"
        if isinstance(op, (ast.Eq, ast.NotEq)):
            if constant is not None and constant.value is None:
                return "W2"
            if constant is not None and isinstance(constant.value, bool):
                return "W3"
            return "S1"
        if isinstance(op, _ORDERING_OPS):
            return "S1"
    return "W3"


def _signals_in_assert(test: ast.expr) -> list[str]:
    if isinstance(test, ast.BoolOp):
        out: list[str] = []
        for value in test.values:
            out.extend(_signals_in_assert(value))
        return out
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        return _signals_in_assert(test.operand)
    if isinstance(test, ast.Compare):
        return [_signal_for_compare(test)]
    if isinstance(test, ast.Call):
        signal = _signal_for_call(test)
        if signal:
            return [signal]
        leaf = _dotted(test.func).split(".")[-1]
        if leaf == "isinstance":
            return ["S2"]
        return ["W3"]
    if isinstance(test, ast.Constant):
        # `assert True` executes nothing and proves nothing.
        return ["W1"]
    if isinstance(test, (ast.Name, ast.Attribute, ast.Subscript)):
        return ["W2"]
    return ["W3"]


def _verdict(signals: list[str]) -> str:
    strong = [s for s in signals if s.startswith("S")]
    if len(strong) >= 2:
        return "S3"
    if "S1" in strong:
        return "S1"
    if "S2" in strong:
        return "S2"
    for weak in ("W5", "W4", "W3", "W2"):
        if weak in signals:
            return weak
    return "W1"


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class TestOracle:
    name: str
    line: int
    verdict: str
    signals: list[str] = field(default_factory=list)
    assertions: int = 0

    @property
    def is_strong(self) -> bool:
        return self.verdict.startswith("S")

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.verdict, self.verdict)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "line": self.line,
            "verdict": self.verdict,
            "label": self.label,
            "strong": self.is_strong,
            "signals": sorted(set(self.signals)),
            "assertions": self.assertions,
        }


@dataclass
class FileOracles:
    path: str
    tests: list[TestOracle] = field(default_factory=list)
    parse_error: str = ""
    is_new_file: bool = False

    @property
    def strong(self) -> int:
        return sum(1 for t in self.tests if t.is_strong)

    @property
    def weak(self) -> int:
        return len(self.tests) - self.strong

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "is_new_file": self.is_new_file,
            "parse_error": self.parse_error,
            "tests": [t.as_dict() for t in self.tests],
            "strong": self.strong,
            "weak": self.weak,
        }


@dataclass
class OracleReport:
    files: list[FileOracles] = field(default_factory=list)
    mode: str = "paths"
    scanned_files: int = 0

    @property
    def tests(self) -> list[TestOracle]:
        return [t for f in self.files for t in f.tests]

    @property
    def total(self) -> int:
        return len(self.tests)

    @property
    def strong(self) -> int:
        return sum(1 for t in self.tests if t.is_strong)

    @property
    def weak(self) -> int:
        return self.total - self.strong

    @property
    def strong_rate(self) -> float | None:
        """None, not 0.0, when nothing was scanned.

        A rate of zero says every test is weak. None says no test was seen.
        Those are different claims and the caller is not allowed to confuse
        them.
        """
        if not self.total:
            return None
        return self.strong / self.total

    def by_category(self) -> dict[str, int]:
        counts = {c: 0 for c in CATEGORIES}
        for t in self.tests:
            counts[t.verdict] = counts.get(t.verdict, 0) + 1
        return counts

    def weak_new_files(self) -> list[FileOracles]:
        return [f for f in self.files
                if f.is_new_file and f.tests and f.strong == 0]

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "taxonomy": "arXiv:2606.18168 W1-W5 / S1-S3",
            "files_scanned": self.scanned_files,
            "files": [f.as_dict() for f in self.files],
            "totals": {
                "tests": self.total,
                "strong": self.strong,
                "weak": self.weak,
                "strong_rate": self.strong_rate,
                "by_category": self.by_category(),
            },
            "weak_new_files": [f.path for f in self.weak_new_files()],
        }


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_function(name: str, fn: ast.AST) -> TestOracle:
    signals: list[str] = []
    assertions = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Assert):
            assertions += 1
            signals.extend(_signals_in_assert(node.test))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.context_expr, ast.Call):
                    signal = _signal_for_call(item.context_expr)
                    if signal:
                        assertions += 1
                        signals.append(signal)
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            signal = _signal_for_call(node.value)
            if signal:
                assertions += 1
                signals.append(signal)
    line = getattr(fn, "lineno", 0)
    return TestOracle(name=name, line=line, verdict=_verdict(signals),
                      signals=signals, assertions=assertions)


def _test_functions(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    out: list[tuple[str, ast.AST]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                out.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if sub.name.startswith("test"):
                        out.append((f"{node.name}.{sub.name}", sub))
    return out


def scan_source(source: str, path: str) -> FileOracles:
    """Classify every test function in one file. Pure, deterministic, offline."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        # The message is the exception type only. SyntaxError carries the
        # offending source line in `.text`, and no reporting path in jittest
        # emits source.
        return FileOracles(path=path, tests=[],
                           parse_error=f"{type(exc).__name__}: file could not be parsed")
    tests = [_scan_function(name, fn) for name, fn in _test_functions(tree)]
    tests.sort(key=lambda t: (t.line, t.name))
    return FileOracles(path=path, tests=tests)


def _relative(repo: Path, target: Path) -> str:
    try:
        return target.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return target.as_posix()


def scan_paths(repo: Path | str, paths: list[str]) -> OracleReport:
    """Scan explicit files, or every test file under the given directories."""
    root = Path(repo).resolve()
    candidates: list[Path] = []
    for raw in paths:
        target = Path(raw)
        if not target.is_absolute():
            target = root / raw
        if target.is_dir():
            candidates.extend(
                q for q in sorted(target.rglob("*.py"))
                if is_probably_test_file(q.as_posix())
            )
        elif target.is_file():
            candidates.append(target)
        else:
            raise OracleScanError(f"no such file or directory: {raw}")

    results: list[FileOracles] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key in seen:
            continue
        seen.add(key)
        try:
            source = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            results.append(FileOracles(
                path=_relative(root, candidate), tests=[],
                parse_error=f"{type(exc).__name__}: file could not be read"))
            continue
        results.append(scan_source(source, _relative(root, candidate)))

    results.sort(key=lambda f: f.path)
    return OracleReport(files=results, mode="paths", scanned_files=len(results))


def scan_changed(repo: Path | str, base: str, head: str) -> OracleReport:
    """Scan only the test files this pull request touched.

    This is the CI shape. It answers the reviewer's question - "are the tests
    that arrived with this change worth anything" - rather than auditing a
    codebase somebody inherited.
    """
    try:
        diff_text = git_diff(repo, base, head)
    except GitError as exc:
        raise OracleScanError(str(exc)) from exc

    results: list[FileOracles] = []
    for fd in parse_unified_diff(diff_text):
        if fd.is_deleted or not fd.path.endswith(".py"):
            continue
        if not is_safe_repo_path(fd.path):
            continue
        if not is_probably_test_file(fd.path):
            continue
        source = git_show(repo, head, fd.path)
        if not source.strip():
            continue
        found = scan_source(source, fd.path)
        found.is_new_file = fd.is_new
        results.append(found)

    results.sort(key=lambda f: f.path)
    return OracleReport(files=results, mode="changed", scanned_files=len(results))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _rate_text(report: OracleReport) -> str:
    rate = report.strong_rate
    if rate is None:
        return "no test functions were scanned, so there is no rate to report"
    return (f"{report.strong}/{report.total} tests carry a strong oracle "
            f"({rate * 100:.0f}%)")


def to_terminal(report: OracleReport) -> str:
    lines = ["jittest oracle scan", ""]
    if not report.files:
        lines.append("  no test files were scanned.")
        if report.mode == "changed":
            lines.append("  this diff did not add or modify a test file.")
        lines.append(f"  {_rate_text(report)}")
        return "\n".join(lines)

    for f in report.files:
        marker = " (new file)" if f.is_new_file else ""
        lines.append(f"  {f.path}{marker}")
        if f.parse_error:
            lines.append(f"      ! {f.parse_error}")
            continue
        if not f.tests:
            lines.append("      (no test functions)")
            continue
        for t in f.tests:
            flag = "ok  " if t.is_strong else "WEAK"
            lines.append(f"      [{flag}] {t.verdict}  line {t.line:>4}  "
                         f"{t.name} - {t.label}")
        lines.append("")

    lines.append(f"  {_rate_text(report)}")
    counts = report.by_category()
    breakdown = "  ".join(f"{c}:{counts[c]}" for c in CATEGORIES if counts[c])
    if breakdown:
        lines.append(f"  {breakdown}")
    for f in report.weak_new_files():
        lines.append(f"  ! {f.path} is a new test file with no strong oracle.")
    return "\n".join(lines)


def to_markdown(report: OracleReport) -> str:
    head = ["### jittest oracle scan", ""]
    if not report.files:
        head.append("No test files were added or modified in this change.")
        head.append("")
        head.append(_rate_text(report) + ".")
        return "\n".join(head)

    head.append(_rate_text(report) + ".")
    head.append("")
    weak = [(f, t) for f in report.files for t in f.tests if not t.is_strong]
    if weak:
        head.append("| file | test | line | oracle |")
        head.append("| --- | --- | --- | --- |")
        for f, t in weak:
            head.append(f"| `{f.path}` | `{t.name}` | {t.line} | "
                        f"{t.verdict} - {t.label} |")
        head.append("")
    for f in report.weak_new_files():
        head.append(f"- **`{f.path}`** is a new test file and not one of its "
                    f"tests asserts a value.")
    head.append("")
    head.append("<sub>Categories follow arXiv:2606.18168. A weak oracle is not "
                "automatically a defect - a smoke test can be deliberate - but "
                "it should be a decision rather than an accident.</sub>")
    return "\n".join(head)
