"""Anti-Fabrication Linter CI Test.

Scans eval/ and src/jittest/phase_d/ to enforce:
1. No direct assignment of hardcoded final_disposition literals in eval harnesses or pipeline steps.
2. No hardcoded ExecutionTrace outcomes (e.g. base_trace = ExecutionTrace(outcome="PASS"...)) outside parsing code.
3. No hardcoded report metrics (median_cost_usd, p95_runtime_s) as typed literals in report dictionaries outside calculation functions.
"""

import ast
import re
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
            # Check if outcome is assigned a literal string like "PASS" or "FAIL_EXCEPTION" directly
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
