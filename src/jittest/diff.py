"""Diff parsing and change-target extraction. Standard library only.

We parse unified diffs ourselves rather than depending on `unidiff`, for one
unglamorous reason: jittest runs inside other people's CI, and every dependency
we add is a resolver conflict waiting to happen in somebody's locked project.
A unified diff is a 90-line parser. It is not worth a dependency.

The unit of work is a *symbol*, not a file. A pull request that touches 40
files usually changes six functions that matter, and a function is the largest
unit a model can reason about precisely and the smallest unit a reviewer cares
about.
"""
from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "Hunk", "FileDiff", "ChangeTarget", "parse_unified_diff", "enclosing_symbols",
    "extract_targets", "is_probably_test_file", "git_diff", "git_show", "TEST_DIRS",
]

_DIFF_GIT = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_HUNK = re.compile(r"^@@ -(?P<os>\d+)(?:,(?P<ol>\d+))? \+(?P<ns>\d+)(?:,(?P<nl>\d+))? @@")
TEST_DIRS = {"test", "tests", "testing", "__tests__"}


@dataclass
class Hunk:
    old_start: int
    new_start: int
    added: list[int] = field(default_factory=list)     # line numbers on the new side
    removed: list[int] = field(default_factory=list)   # line numbers on the old side


@dataclass
class FileDiff:
    path: str
    old_path: str = ""
    is_new: bool = False
    is_deleted: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self) -> list[int]:
        return [n for h in self.hunks for n in h.added]

    @property
    def removed_lines(self) -> list[int]:
        return [n for h in self.hunks for n in h.removed]


@dataclass
class ChangeTarget:
    file_path: str
    symbol: str
    start_line: int
    end_line: int
    added_lines: list[int]
    removed_lines: list[int]
    source_after: str
    source_before: str = ""

    @property
    def churn(self) -> int:
        return len(self.added_lines) + len(self.removed_lines)

    @property
    def modifies_existing(self) -> bool:
        """Editing working code is riskier than adding new code beside it."""
        return bool(self.source_before.strip())

    @property
    def qualified(self) -> str:
        return f"{self.file_path}::{self.symbol}"


def parse_unified_diff(text: str) -> list[FileDiff]:
    files: list[FileDiff] = []
    current: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0

    for line in text.splitlines():
        m = _DIFF_GIT.match(line)
        if m:
            current = FileDiff(path=m.group("b"), old_path=m.group("a"))
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if line.startswith("new file mode"):
            current.is_new = True
            continue
        if line.startswith("deleted file mode"):
            current.is_deleted = True
            continue
        if line.startswith("--- "):
            if line.strip() == "--- /dev/null":
                current.is_new = True
            continue
        if line.startswith("+++ "):
            if line.strip() == "+++ /dev/null":
                current.is_deleted = True
            continue

        m = _HUNK.match(line)
        if m:
            old_no = int(m.group("os"))
            new_no = int(m.group("ns"))
            hunk = Hunk(old_start=old_no, new_start=new_no)
            current.hunks.append(hunk)
            continue
        if hunk is None:
            continue

        if line.startswith("+"):
            hunk.added.append(new_no)
            new_no += 1
        elif line.startswith("-"):
            hunk.removed.append(old_no)
            old_no += 1
        elif line.startswith("\\"):        # "\ No newline at end of file"
            continue
        else:
            old_no += 1
            new_no += 1

    return [f for f in files if f.hunks]


def is_probably_test_file(path: str) -> bool:
    p = path.replace("\\", "/")
    parts = p.split("/")
    name = parts[-1]
    if name == "conftest.py":
        return True
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return any(part in TEST_DIRS for part in parts[:-1])


def enclosing_symbols(source: str) -> list[tuple[str, int, int]]:
    """Every function and class in the file as (dotted name, start, end)."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    found: list[tuple[str, int, int]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                start = min([child.lineno] + [d.lineno for d in child.decorator_list])
                end = getattr(child, "end_lineno", child.lineno) or child.lineno
                found.append((name, start, end))
                walk(child, name)

    walk(tree, "")
    return found


def _innermost(symbols: list[tuple[str, int, int]], line: int) -> tuple[str, int, int] | None:
    covering = [s for s in symbols if s[1] <= line <= s[2]]
    if not covering:
        return None
    return min(covering, key=lambda s: s[2] - s[1])


def _slice(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    return "\n".join(lines[start - 1:end])


def git_diff(repo: Path | str, base: str, head: str) -> str:
    """Three-dot diff (merge-base), falling back to two-dot for shallow clones."""
    for spec in (f"{base}...{head}", f"{base}..{head}"):
        res = subprocess.run(
            ["git", "-C", str(repo), "diff", "--unified=3", "--no-color", spec],
            capture_output=True, text=True,
        )
        if res.returncode == 0:
            return res.stdout
    return ""


def git_show(repo: Path | str, rev: str, path: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo), "show", f"{rev}:{path}"],
        capture_output=True, text=True,
    )
    return res.stdout if res.returncode == 0 else ""


def extract_targets(
    diff_text: str,
    repo: Path | str | None = None,
    base: str = "",
    head: str = "",
    include_new_files: bool = True,
) -> list[ChangeTarget]:
    """Turn a diff into the list of changed Python symbols worth testing.

    Without a repo and a head revision we cannot read the post-change source,
    and a target without source is useless to the generator, so we return
    nothing rather than something misleading.
    """
    if repo is None or not head:
        return []

    targets: list[ChangeTarget] = []
    for fd in parse_unified_diff(diff_text):
        if fd.is_deleted or not fd.path.endswith(".py"):
            continue
        if is_probably_test_file(fd.path):
            continue
        if fd.is_new and not include_new_files:
            continue

        after = git_show(repo, head, fd.path)
        if not after.strip():
            continue
        before = "" if fd.is_new else git_show(repo, base, fd.path)

        symbols_after = enclosing_symbols(after)
        symbols_before = {name: (s, e) for name, s, e in enclosing_symbols(before)}

        grouped: dict[str, dict] = {}
        for line in fd.added_lines:
            hit = _innermost(symbols_after, line)
            name, start, end = hit if hit else ("<module>", 1, len(after.splitlines()))
            entry = grouped.setdefault(
                name, {"start": start, "end": end, "added": [], "removed": []})
            entry["added"].append(line)

        # Pure deletions still change behaviour; attribute them to the symbol
        # that used to contain them, if it still exists.
        for line in fd.removed_lines:
            hit_before = _innermost(
                [(n, s, e) for n, (s, e) in symbols_before.items()], line)
            if not hit_before:
                continue
            name = hit_before[0]
            after_pos = next((s for s in symbols_after if s[0] == name), None)
            if not after_pos:
                continue
            entry = grouped.setdefault(
                name, {"start": after_pos[1], "end": after_pos[2],
                       "added": [], "removed": []})
            entry["removed"].append(line)

        for name, info in grouped.items():
            source_after = _slice(after, info["start"], info["end"])
            source_before = ""
            if name in symbols_before:
                bs, be = symbols_before[name]
                source_before = _slice(before, bs, be)
            targets.append(ChangeTarget(
                file_path=fd.path, symbol=name,
                start_line=info["start"], end_line=info["end"],
                added_lines=sorted(info["added"]),
                removed_lines=sorted(info["removed"]),
                source_after=source_after, source_before=source_before,
            ))

    return targets
