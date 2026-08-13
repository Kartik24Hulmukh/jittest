"""Generate Four-Quadrant Public Evidence Artifacts.

Generates one signed evidence JSON artifact for each of the four verdict quadrants:
1. proven_catch (catching)
2. refuted (head_failed_base_failed_latent)
3. non_discriminating (head_passed)
4. inconclusive (base_uncollectable)

Artifacts are saved under docs/evidence/quadrants/.
"""

import sys
import tempfile
from pathlib import Path

from jittest.receipt import verify_receipt
from jittest.verify import verify_test

SCRIPT_DIR = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    FLASK_REPO = Path(r"C:\Users\praja\src\flask")
else:
    FLASK_REPO = Path("/mnt/c/Users/praja/src/flask")
    if not FLASK_REPO.exists():
        FLASK_REPO = Path.home() / "src" / "flask"

QUADRANTS_DIR = SCRIPT_DIR / "docs" / "evidence" / "quadrants"
FIXTURES_DIR = SCRIPT_DIR / "tests" / "fixtures" / "v0.2_gate"

BASE_SHA = "12e95c93b488725f80753f34b2e0d24838ca4646"
HEAD_SHA = "d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9"


def main():
    QUADRANTS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # 1. PROVEN_CATCH
        out_pc = QUADRANTS_DIR / "proven_catch_evidence.json"
        print("Generating proven_catch quadrant...")
        evidence_pc, exit_pc = verify_test(
            repo_path=FLASK_REPO,
            base_ref=BASE_SHA,
            head_ref=HEAD_SHA,
            test_file_path=FIXTURES_DIR / "fixture_flask_01.py",
            output_path=out_pc,
            no_sandbox=True,
        )
        ok_pc, _ = verify_receipt(out_pc)
        print(f"  proven_catch: verdict={evidence_pc['verdict']}, disposition={evidence_pc['disposition']}, signature_valid={ok_pc}")

        # 2. REFUTED
        refuted_test = tmp / "test_refuted.py"
        refuted_test.write_text("def test_refuted():\n    assert False, 'Fails on both base and head'\n", encoding="utf-8")
        out_ref = QUADRANTS_DIR / "refuted_evidence.json"
        print("Generating refuted quadrant...")
        evidence_ref, exit_ref = verify_test(
            repo_path=FLASK_REPO,
            base_ref=BASE_SHA,
            head_ref=HEAD_SHA,
            test_file_path=refuted_test,
            output_path=out_ref,
            no_sandbox=True,
        )
        ok_ref, _ = verify_receipt(out_ref)
        print(f"  refuted: verdict={evidence_ref['verdict']}, disposition={evidence_ref['disposition']}, signature_valid={ok_ref}")

        # 3. NON_DISCRIMINATING
        nondisc_test = tmp / "test_nondisc.py"
        nondisc_test.write_text("def test_nondisc():\n    assert True, 'Passes on both base and head'\n", encoding="utf-8")
        out_nd = QUADRANTS_DIR / "non_discriminating_evidence.json"
        print("Generating non_discriminating quadrant...")
        evidence_nd, exit_nd = verify_test(
            repo_path=FLASK_REPO,
            base_ref=BASE_SHA,
            head_ref=HEAD_SHA,
            test_file_path=nondisc_test,
            output_path=out_nd,
            no_sandbox=True,
        )
        ok_nd, _ = verify_receipt(out_nd)
        print(f"  non_discriminating: verdict={evidence_nd['verdict']}, disposition={evidence_nd['disposition']}, signature_valid={ok_nd}")

        # 4. INCONCLUSIVE
        inconclusive_test = tmp / "test_inconclusive.py"
        inconclusive_test.write_text("def test_syntax_error(\n    invalid syntax here!!\n", encoding="utf-8")
        out_inc = QUADRANTS_DIR / "inconclusive_evidence.json"
        print("Generating inconclusive quadrant...")
        evidence_inc, exit_inc = verify_test(
            repo_path=FLASK_REPO,
            base_ref=BASE_SHA,
            head_ref=HEAD_SHA,
            test_file_path=inconclusive_test,
            output_path=out_inc,
            no_sandbox=True,
        )
        ok_inc, _ = verify_receipt(out_inc)
        print(f"  inconclusive: verdict={evidence_inc['verdict']}, disposition={evidence_inc['disposition']}, signature_valid={ok_inc}")

    print("\nFOUR-QUADRANT EVIDENCE GENERATION COMPLETE!")


if __name__ == "__main__":
    main()
