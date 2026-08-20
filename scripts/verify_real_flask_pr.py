"""Verify real public Flask PR #6133 end-to-end and publish signed evidence artifact.

Target: pallets/flask PR #6133
Base SHA: 3596b1ab61cea85edb8970e83ff61daa073facf8
Head SHA: 89992954ec71b594b1b911f98977cdc8ad46a057
Test file: tests/test_basic.py

Evidence saved to docs/evidence/pr/flask_pr_evidence.json
"""

import sys
from pathlib import Path

from jittest.receipt import verify_receipt
from jittest.verify import verify_test

SCRIPT_DIR = Path(__file__).resolve().parent.parent

FLASK_REPO = Path.home() / "src" / "flask"

EVIDENCE_PR_DIR = SCRIPT_DIR / "docs" / "evidence" / "pr"
OUT_FILE = EVIDENCE_PR_DIR / "flask_pr_evidence.json"


def main():
    EVIDENCE_PR_DIR.mkdir(parents=True, exist_ok=True)
    test_path = FLASK_REPO / "tests" / "test_basic.py"

    print("=== RUNNING END-TO-END E2E PROOF ON REAL PUBLIC FLASK PR #6133 ===")
    print(f"Repo: {FLASK_REPO}")
    print("PR #6133 (base=3596b1ab, head=89992954)")
    print(f"Test: {test_path}")

    evidence, exit_code = verify_test(
        repo_path=FLASK_REPO,
        base_ref="3596b1ab61cea85edb8970e83ff61daa073facf8",
        head_ref="89992954ec71b594b1b911f98977cdc8ad46a057",
        test_file_path=test_path,
        output_path=OUT_FILE,
        no_sandbox=True,
    )

    ok, msg = verify_receipt(OUT_FILE)

    print("\nE2E PR VERIFICATION COMPLETE!")
    print(f"  Exit code: {exit_code}")
    print(f"  Verdict: {evidence['verdict']}")
    print(f"  Disposition: {evidence['disposition']}")
    print(f"  Receipt valid: {ok} ({msg})")
    print(f"  Artifact written to: {OUT_FILE}")


if __name__ == "__main__":
    main()
