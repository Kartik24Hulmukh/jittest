"""v0.2 Hard Gate Execution Script.

Runs jittest verify across 5 real Flask manifest profiles from r2b-bug-packet-manifest.json
using candidate catching tests and publishes 5/5 proven_catch signed evidence artifacts to docs/evidence/v0.2/.
"""

import sys
from pathlib import Path

from jittest.receipt import verify_receipt
from jittest.verify import verify_test

SCRIPT_DIR = Path(__file__).resolve().parent

if sys.platform == "win32":
    FLASK_REPO = Path(r"C:\Users\praja\src\flask")
else:
    FLASK_REPO = Path("/mnt/c/Users/praja/src/flask")
    if not FLASK_REPO.exists():
        FLASK_REPO = Path.home() / "src" / "flask"

DOCS_EVIDENCE_DIR = SCRIPT_DIR / "docs" / "evidence" / "v0.2"
FIXTURES_DIR = SCRIPT_DIR / "tests" / "fixtures" / "v0.2_gate"

PROFILES = [
    {
        "id": "flask_01",
        "name": "bug_flask_01 (cli)",
        "base_sha": "12e95c93b488725f80753f34b2e0d24838ca4646",
        "head_sha": "d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9",
        "test_file": FIXTURES_DIR / "test_flask_01.py",
    },
    {
        "id": "flask_02",
        "name": "bug_flask_02 (json)",
        "base_sha": "25642fd1fd65985fc98f95e64bc2c7ff353d6c2b",
        "head_sha": "64dd0809c2fc732ed30539235232a268f9bd96ac",
        "test_file": FIXTURES_DIR / "test_flask_02.py",
    },
    {
        "id": "flask_03",
        "name": "bug_flask_03 (sessions)",
        "base_sha": "fb54159861708558b5f5658ebdc14709d984361c",
        "head_sha": "941efd4a36ed0f27e13758874f95e3aa1d3ee163",
        "test_file": FIXTURES_DIR / "test_flask_03.py",
    },
    {
        "id": "flask_04",
        "name": "bug_flask_04 (blueprints)",
        "base_sha": "4995a775df21a206b529403bc30d71795a994fd4",
        "head_sha": "07c7d5730a2685ef2281cc635e289685e5c3d478",
        "test_file": FIXTURES_DIR / "test_flask_04.py",
    },
    {
        "id": "flask_05",
        "name": "bug_flask_05 (views)",
        "base_sha": "c62b03bcfd6e6440f8195e02f4678488e16121ac",
        "head_sha": "96800fb673cb7b2d75476096798e701e3e6d26bc",
        "test_file": FIXTURES_DIR / "test_flask_05.py",
    },
]


def main():
    DOCS_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    results = []

    print("=== STARTING V0.2 HARD GATE EXECUTION ACROSS 5 REAL FLASK PROFILES ===")

    for prof in PROFILES:
        prof_id = prof["id"]
        out_file = DOCS_EVIDENCE_DIR / f"{prof_id}_evidence.json"
        
        print(f"\nRunning verify_test on profile {prof['name']}...")
        print(f"  Base: {prof['base_sha'][:8]} | Head: {prof['head_sha'][:8]}")

        evidence, exit_code = verify_test(
            repo_path=FLASK_REPO,
            base_ref=prof["base_sha"],
            head_ref=prof["head_sha"],
            test_file_path=prof["test_file"],
            output_path=out_file,
            timeout_s=120,
            no_sandbox=True,  # local verification run
        )

        ok, msg = verify_receipt(out_file)

        print(f"  Result: exit_code={exit_code}, verdict={evidence['verdict']}, disposition={evidence['disposition']}")
        print(f"  Receipt Signature Verification: valid={ok} ({msg})")

        results.append({
            "id": prof_id,
            "name": prof["name"],
            "exit_code": exit_code,
            "verdict": evidence["verdict"],
            "proven_catch": evidence.get("proven_catch", False),
            "disposition": evidence["disposition"],
            "receipt_valid": ok,
            "artifact_path": str(out_file),
        })

    print("\n=== V0.2 HARD GATE SUMMARY ===")
    for r in results:
        status_label = "PROVEN_CATCH" if r["proven_catch"] else r["verdict"]
        print(f"[{'PASS' if r['proven_catch'] else 'FAIL'}] {r['name']}: {status_label} ({r['disposition']}) -> {r['artifact_path']}")

    all_proven = all(r["proven_catch"] for r in results)
    print(f"\nHard Gate Status: {'PASSED 5/5 PROVEN_CATCH PROFILES' if all_proven else 'FAILED'}")
    return 0 if all_proven else 1


if __name__ == "__main__":
    raise SystemExit(main())

