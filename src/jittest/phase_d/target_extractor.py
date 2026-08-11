"""Target Extraction Module for Phase D Differential Explorer.

Extracts real target_file and target_symbol from repository diffs and manifest rows.
Never defaults target_file to src/flask/app.py or target_symbol to bug_flask_0N.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any


def extract_target_for_row(row: dict[str, Any], repo_path: Path) -> tuple[bool, str, str, str, str]:
    """Extract (eligible, exclusion_reason, target_file, target_symbol, diff_text).

    Strategy:
    1. Read primary_path from independence_receipt or derive changed files from git diff base..head.
    2. Filter to valid production Python files.
    3. Extract modified function/class symbol from git diff hunk headers or modified lines.
    4. Fall back to AST parsing top-level functions/classes in target_file if diff has no explicit def/class header.
    """
    primary_path = row.get("independence_receipt", {}).get("primary_path", "")
    base_sha = row.get("derived_base_sha") or row.get("real_buggy_sha") or row.get("base_sha", "")
    head_sha = row.get("derived_head_sha") or row.get("real_fixed_sha") or row.get("head_sha", "")

    if not base_sha or not head_sha:
        return False, "missing base_sha or head_sha in row manifest", "", "", ""

    # 1. Get changed files via git diff
    cmd_files = ["git", "-C", str(repo_path), "diff", base_sha, head_sha, "--name-only"]
    res_files = subprocess.run(cmd_files, capture_output=True, text=True)
    changed_files = [
        f for f in res_files.stdout.splitlines()
        if f.endswith(".py") and not f.startswith("tests/") and not f.startswith("examples/") and not f.startswith("docs/")
    ]

    target_file = ""
    if primary_path and (repo_path / primary_path).exists() and not primary_path.startswith("tests/"):
        target_file = primary_path
    elif changed_files:
        target_file = changed_files[0]

    if not target_file or not (repo_path / target_file).exists():
        return False, f"no production Python target file changed or found for row {row['row_id']}", "", "", ""

    # 2. Get git diff for target_file
    cmd_diff = ["git", "-C", str(repo_path), "diff", base_sha, head_sha, "--", target_file]
    res_diff = subprocess.run(cmd_diff, capture_output=True, text=True)
    diff_text = res_diff.stdout

    # If diff on target_file is empty (e.g. primary_path was unchanged between base and head), try diff base~1..base
    if not diff_text.strip():
        cmd_diff_base = ["git", "-C", str(repo_path), "diff", f"{base_sha}~1", base_sha, "--", target_file]
        res_diff_base = subprocess.run(cmd_diff_base, capture_output=True, text=True)
        if res_diff_base.stdout.strip():
            diff_text = res_diff_base.stdout

    # 3. Extract symbol from diff
    symbol = ""
    for line in diff_text.splitlines():
        if line.startswith("@@") and ("def " in line or "class " in line):
            m = re.search(r"(?:def|class)\s+([a-zA-Z0-9_]+)", line)
            if m:
                symbol = m.group(1)
                break
        elif (line.startswith("+") or line.startswith("-")) and not line.startswith("+++") and not line.startswith("---"):
            m = re.search(r"^\s*(?:def|class)\s+([a-zA-Z0-9_]+)", line[1:])
            if m:
                symbol = m.group(1)
                break

    # 4. AST fallback
    if not symbol:
        try:
            tree = ast.parse((repo_path / target_file).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    symbol = node.name
                    break
        except Exception:
            pass

    if not symbol:
        symbol = Path(target_file).stem

    return True, "", target_file, symbol, diff_text
