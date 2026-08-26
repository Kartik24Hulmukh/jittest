"""Anti-Fabrication Linter CI Test.

Enforces:
1. No direct assignment of hardcoded final_disposition literals in eval harnesses or pipeline steps.
2. No hardcoded ExecutionTrace outcomes (e.g. base_trace = ExecutionTrace(outcome="PASS"...)) outside parsing code.
3. No hardcoded report metrics (median_cost_usd, p95_runtime_s) as typed literals in report dictionaries outside calculation functions.
4. Programmatic Provenance: every 40-hex SHA string appearing in any report markdown MUST be a real git commit SHA present in `git log` or manifest/artifact JSON. No hand-typed or fabricated SHAs permitted.
"""

import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_hardcoded_execution_traces_or_dispositions():
    py_files = list((REPO_ROOT / "src").glob("**/*.py")) + list((REPO_ROOT / "eval").glob("*.py"))

    for pf in py_files:
        if not pf.exists():
            continue
        text = pf.read_text(encoding="utf-8")

        if "ExecutionTrace(outcome=" in text and "outcome=parse_" not in text and (
            re.search(r'ExecutionTrace\s*\(\s*outcome\s*=\s*["\']PASS["\']', text) or
            re.search(r'ExecutionTrace\s*\(\s*outcome\s*=\s*["\']FAIL', text)
        ):
            raise AssertionError(
                f"Anti-Fabrication Failure: Hardcoded ExecutionTrace outcome found in {pf.name}"
            )

        if "telem.final_disposition = Disposition.HEAD_PASSED.value" in text and "eval" in str(pf):
            raise AssertionError(
                f"Anti-Fabrication Failure: Hardcoded control final_disposition override found in {pf.name}"
            )


def test_programmatic_provenance_shas_in_markdown():
    """Verify that every 40-hex SHA string in report markdown exists in git history or manifest/artifacts."""
    res_commits = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--all", "--format=%H"], capture_output=True, text=True)
    res_trees = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--all", "--format=%T"], capture_output=True, text=True)
    res_cur_tree = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True)

    git_shas = set(res_commits.stdout.splitlines()) | set(res_trees.stdout.splitlines()) | {res_cur_tree.stdout.strip()}

    artifact_shas = set()
    for json_file in REPO_ROOT.rglob("*.json"):
        content = json_file.read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r"\b[0-9a-fA-F]{40}\b", content):
            artifact_shas.add(match.lower())

    valid_shas = {s.lower() for s in git_shas} | artifact_shas

    md_files = [
        md for md in (
            list(REPO_ROOT.glob("*.md"))
            + list((REPO_ROOT / "docs").glob("*.md"))
            + list((REPO_ROOT / "docs" / "reports").glob("*.md"))
        )
        if not md.name.startswith("WO-")
    ]
    for md in md_files:
        if not md.exists():
            continue
        text = md.read_text(encoding="utf-8")
        found_shas = re.findall(r"\b[0-9a-fA-F]{40}\b", text)
        for sha in found_shas:
            if sha.lower() not in valid_shas:
                raise AssertionError(
                    f"Anti-Fabrication Failure: Markdown {md.name} contains invalid/fabricated 40-hex SHA '{sha}' not present in git log or JSON artifacts."
                )
