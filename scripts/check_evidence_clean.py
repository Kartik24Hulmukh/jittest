#!/usr/bin/env python3
"""Fail CI if tests modify committed receipts or leave new evidence in the checkout.

Run AFTER the full suite, from any directory. Historical committed receipts stay
versioned; tests must send all new evidence to temporary output directories.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    result = subprocess.run(
        [
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            "jittest-evidence",
            "docs/evidence",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        print(result.stderr.strip())
        return 1
    if result.stdout.strip():
        print("Evidence checkout polluted; use temporary output directories:")
        print(result.stdout.strip())
        return 1
    print("evidence-clean: committed receipts unchanged; no new evidence files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
