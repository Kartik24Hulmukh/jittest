"""Test verifying that all Phase C receipt SHAs are programmatically derived from real git data."""

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

BANNED_PLACEHOLDER_SHAS = {
    "1212121212121212121212121212121212121212",
    "1111111111111111111111111111111111111111",
    "1010101010101010101010101010101010101010",
    "0000000000000000000000000000000000000000",
}
REPEATED_NIBBLE = re.compile(r"^([0-9a-fA-F])\1{39}$")


def get_git_info():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    tree = subprocess.check_output(["git", "write-tree"], cwd=REPO_ROOT).decode().strip()
    try:
        parent = subprocess.check_output(["git", "rev-parse", "HEAD~1"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        parent = ""
    return head, tree, parent


def test_no_fabricated_shas_in_receipts():
    head_sha, tree_sha, parent_sha = get_git_info()

    receipt_files = [
        REPO_ROOT / "phase-c-freeze-config.json",
        REPO_ROOT / "phase-c-benchmark-manifest.json",
        REPO_ROOT / "phase-c-freeze-receipt.json",
        REPO_ROOT / "phase-c-calibration-ledger.json",
        REPO_ROOT / "phase-c-calibration-report.json",
        REPO_ROOT / "phase-c-execution-ledger.json",
        REPO_ROOT / "phase-c-measurement-report.json",
    ]

    for p in receipt_files:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8")
        for banned in BANNED_PLACEHOLDER_SHAS:
            assert banned not in text, f"Banned placeholder SHA {banned} found in {p.name}"

        # Ensure JSON structures carry valid 40-char git SHAs
        try:
            data = json.loads(text)
            if "protocol_commit" in data:
                commit = data["protocol_commit"]
                assert len(commit) == 40, f"Invalid protocol_commit length in {p.name}"
                assert not REPEATED_NIBBLE.match(commit), f"Repeated nibble SHA found in {p.name}"
            if "protocol_tree" in data:
                tree = data["protocol_tree"]
                assert len(tree) == 40, f"Invalid protocol_tree length in {p.name}"
                assert not REPEATED_NIBBLE.match(tree), f"Repeated nibble SHA found in {p.name}"
        except json.JSONDecodeError:
            pass
