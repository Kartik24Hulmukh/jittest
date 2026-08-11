"""Context compiler for Phase D Differential Explorer.

Compiles rich, bounded target context:
- before/after target source
- added/removed lines
- import and constructor signatures
- accessible caller / public entry point
- up to two nearest existing test FUNCTION BODIES (inlined)
- required fixtures / conftest fragments
- PR / issue / commit context when available
- strict context byte bounding
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class TargetContext:
    target_symbol: str
    target_file: str
    before_source: str = ""
    after_source: str = ""
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    import_signatures: list[str] = field(default_factory=list)
    constructor_signatures: list[str] = field(default_factory=list)
    caller_entry_points: list[str] = field(default_factory=list)
    test_function_bodies: list[str] = field(default_factory=list)
    conftest_fragments: list[str] = field(default_factory=list)
    commit_context: str = ""
    total_bytes: int = 0

    def format_for_prompt(self, max_bytes: int = 32000) -> str:
        parts: list[str] = [
            f"=== TARGET SYMBOL: {self.target_symbol} ({self.target_file}) ===",
        ]

        if self.commit_context:
            parts.append(f"--- Commit/PR Context ---\n{self.commit_context.strip()}")

        if self.before_source:
            parts.append(f"--- BASE (Before) Target Source ---\n{self.before_source.strip()}")

        if self.after_source:
            parts.append(f"--- HEAD (After) Target Source ---\n{self.after_source.strip()}")

        if self.added_lines or self.removed_lines:
            diff_lines = []
            for line in self.removed_lines:
                diff_lines.append(f"- {line}")
            for line in self.added_lines:
                diff_lines.append(f"+ {line}")
            parts.append("--- Line Differences ---\n" + "\n".join(diff_lines))

        if self.import_signatures:
            parts.append("--- Imports & Signatures ---\n" + "\n".join(self.import_signatures))

        if self.constructor_signatures:
            parts.append("--- Constructor Signatures ---\n" + "\n".join(self.constructor_signatures))

        if self.caller_entry_points:
            parts.append("--- Caller / Public Entry Points ---\n" + "\n".join(self.caller_entry_points))

        if self.test_function_bodies:
            parts.append("--- Inlined Nearest Existing Test Function Bodies ---\n" + "\n\n".join(self.test_function_bodies))

        if self.conftest_fragments:
            parts.append("--- Conftest Fixtures ---\n" + "\n\n".join(self.conftest_fragments))

        result = "\n\n".join(parts)
        if len(result.encode("utf-8")) > max_bytes:
            # Truncate cleanly if exceeding max_bytes
            truncated = result.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
            result = truncated + "\n... [Context truncated to fit budget]"

        self.total_bytes = len(result.encode("utf-8"))
        return result


class ContextCompiler:
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)

    def find_nearest_test_bodies(self, target_symbol: str, target_file: str, max_count: int = 2) -> list[str]:
        """Find up to `max_count` nearest test function bodies referencing `target_symbol`."""
        base_name = target_symbol.split(".")[-1]
        test_bodies: list[str] = []

        # Find test directories / files
        test_files = list(self.repo_path.glob("**/test_*.py")) + list(self.repo_path.glob("**/*_test.py"))
        for tf in test_files:
            if len(test_bodies) >= max_count:
                break
            try:
                content = tf.read_text(encoding="utf-8", errors="ignore")
                if base_name not in content and target_symbol not in content:
                    continue

                tree = ast.parse(content, filename=str(tf))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name.startswith("test_") or node.name.endswith("_test"):
                            fn_source = ast.get_source_segment(content, node)
                            if fn_source and (base_name in fn_source or target_symbol in fn_source):
                                # Include file path header above function body
                                inlined = f"# From {tf.relative_to(self.repo_path)}\n{fn_source}"
                                test_bodies.append(inlined)
                                if len(test_bodies) >= max_count:
                                    break
            except Exception:
                continue

        return test_bodies

    def find_conftest_fragments(self, target_file: str) -> list[str]:
        """Find conftest.py fixtures near target_file."""
        fragments: list[str] = []
        target_dir = (self.repo_path / target_file).parent
        curr = target_dir
        while curr >= self.repo_path:
            conftest = curr / "conftest.py"
            if conftest.exists():
                try:
                    text = conftest.read_text(encoding="utf-8", errors="ignore").strip()
                    if text:
                        rel = conftest.relative_to(self.repo_path)
                        fragments.append(f"# From {rel}\n{text}")
                except Exception:
                    pass
            if curr == self.repo_path:
                break
            curr = curr.parent
        return fragments

    def compile_context(
        self,
        target_symbol: str,
        target_file: str,
        before_source: str = "",
        after_source: str = "",
        added_lines: list[str] | None = None,
        removed_lines: list[str] | None = None,
        commit_context: str = "",
        max_bytes: int = 32000,
    ) -> TargetContext:
        ctx = TargetContext(
            target_symbol=target_symbol,
            target_file=target_file,
            before_source=before_source,
            after_source=after_source,
            added_lines=added_lines or [],
            removed_lines=removed_lines or [],
            commit_context=commit_context,
        )

        # Extract import and constructor signatures from after_source or file
        if after_source:
            try:
                tree = ast.parse(after_source)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.Import, ast.ImportFrom)):
                        ctx.import_signatures.append(ast.unparse(node))
                    elif isinstance(node, ast.ClassDef) and node.name in target_symbol:
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                                ctx.constructor_signatures.append(f"class {node.name}:\n    def __init__{ast.unparse(item.args)}:")
            except Exception:
                pass

        ctx.test_function_bodies = self.find_nearest_test_bodies(target_symbol, target_file, max_count=2)
        ctx.conftest_fragments = self.find_conftest_fragments(target_file)
        ctx.format_for_prompt(max_bytes=max_bytes)
        return ctx
