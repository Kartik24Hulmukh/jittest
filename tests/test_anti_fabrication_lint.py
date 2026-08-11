"""Anti-Fabrication Linter CI Test (C-PHASE-D-FIX-2).

Enforces:
1. No direct assignment of hardcoded final_disposition literals in eval harnesses or pipeline steps.
2. No hardcoded ExecutionTrace outcomes (e.g. base_trace = ExecutionTrace(outcome="PASS"...)) outside parsing code.
3. No hardcoded report metrics (median_cost_usd, p95_runtime_s) as typed literals in report dictionaries outside calculation functions.
4. Programmatic Provenance: every 40-hex commit SHA appearing in any report markdown (RESULTS.md, phase-d-preregistration.md) MUST be a real git commit SHA present in `git log --format=%H` or manifest/artifact JSON. No hand-typed or fabricated SHAs permitted.
"""

import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PHASE_D_DIR = REPO_ROOT / "src" / "jittest" / "phase_d"
EVAL_DIR = REPO_ROOT / "eval"


def test_no_hardcoded_execution_traces_or_dispositions():
    py_files = list(PHASE_D_DIR.glob("*.py")) + list(EVAL_DIR.glob("phase_d_*.py"))

    for pf in py_files:
        if not pf.exists():
            continue
        text = pf.read_text(encoding="utf-8")

        # 1. Reject hardcoded ExecutionTrace construction with string literals
        if "ExecutionTrace(outcome=" in text and "outcome=parse_" not in text:
            if re.search(r'ExecutionTrace\s*\(\s*outcome\s*=\s*["\']PASS["\']', text) or \
               re.search(r'ExecutionTrace\s*\(\s*outcome\s*=\s*["\']FAIL', text):
                raise AssertionError(
                    f"Anti-Fabrication Failure: Hardcoded ExecutionTrace outcome found in {pf.name}"
                )

        # 2. Reject direct hardcoded assignment of final_disposition to control rows in eval harnesses
        if "telem.final_disposition = Disposition.HEAD_PASSED.value" in text and "eval" in str(pf):
            raise AssertionError(
                f"Anti-Fabrication Failure: Hardcoded control final_disposition override found in {pf.name}"
            )

        # 3. Reject hardcoded metric dictionary values like "median_cost_usd": 0.012 or "p95_runtime_s": 45.0
        if re.search(r'["\']median_cost_usd["\']\s*:\s*0\.\d+', text) or \
           re.search(r'["\']p95_runtime_s["\']\s*:\s*\d+\.\d+', text):
            raise AssertionError(
                f"Anti-Fabrication Failure: Hardcoded report metric literal found in {pf.name}"
            )


def test_programmatic_provenance_shas_in_markdown():
    """Verify that every 40-hex SHA string in report markdown exists in git history or manifest/artifacts."""
    # Get all valid git commit and tree SHAs from git log & rev-parse
    res_commits = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--format=%H"], capture_output=True, text=True)
    res_trees = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--format=%T"], capture_output=True, text=True)
    res_cur_tree = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD^{tree}"], capture_output=True, text=True)

    git_shas = set(res_commits.stdout.splitlines()) | set(res_trees.stdout.splitlines()) | {res_cur_tree.stdout.strip()}

    # Collect SHAs from manifest and json artifacts
    artifact_shas = set()
    for json_file in REPO_ROOT.glob("*.json"):
        content = json_file.read_text(encoding="utf-8", errors="ignore")
        for match in re.findall(r"\b[0-9a-fA-F]{40}\b", content):
            artifact_shas.add(match.lower())

    valid_shas = {s.lower() for s in git_shas} | artifact_shas

    # Check all markdown files
    md_files = [REPO_ROOT / "RESULTS.md", REPO_ROOT / "phase-d-preregistration.md"]
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
