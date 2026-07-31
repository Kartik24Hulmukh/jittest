"""End-to-end seeded-regression demo for jittest.

Creates a tiny git repository with two commits: a correct ``calc.py`` on the
base commit and a regression (the zero-floor clamp removed) on the head
commit. Then, when jittest is available, it runs the full pipeline against
that pair with ``--dry-run`` - no API key, no network, no cost.

    python examples/seeded_regression_demo.py

Pass ``--keep`` to leave the demo repository on disk; its path is printed.
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GOOD = '''def apply_discount(price: float, pct: float) -> float:
    """Apply a percentage discount; the result never goes below zero."""
    return max(0.0, price * (1 - pct / 100))
'''

BAD = '''def apply_discount(price: float, pct: float) -> float:
    """Apply a percentage discount."""
    return price * (1 - pct / 100)
'''


def git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def build_repo(root: Path) -> Path:
    repo = root / "demo-shop"
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "demo@jittest.dev")
    git(repo, "config", "user.name", "jittest demo")
    (repo / "calc.py").write_text(GOOD, encoding="utf-8")
    git(repo, "add", "calc.py")
    git(repo, "commit", "-q", "-m", "Add discount calculation")
    (repo / "calc.py").write_text(BAD, encoding="utf-8")
    git(repo, "add", "calc.py")
    git(repo, "commit", "-q", "-m", "Simplify discount calculation")
    return repo


def run_jittest(repo: Path) -> int:
    # --risk-threshold 0.0 widens the net so the single changed symbol is
    # always analysed; the demo is about the pipeline's mechanics, not the
    # risk gate's calibration.
    args = ["run", "--repo", str(repo), "--base", "HEAD~1",
            "--head", "HEAD", "--dry-run", "--risk-threshold", "0.0"]
    if shutil.which("jittest"):
        cmd = ["jittest", *args]
    elif importlib.util.find_spec("jittest") is not None:
        cmd = [sys.executable, "-m", "jittest.cli", *args]
    else:
        print("jittest is not installed for this interpreter.")
        print("Install it (`pip install jittest`, or `pip install -e .` from")
        print("a clone) and then run:")
        print(f"  jittest {' '.join(args)}")
        return 2
    print("$ " + " ".join(cmd))
    return subprocess.run(cmd).returncode


def main() -> int:
    keep = "--keep" in sys.argv[1:]
    root = Path(tempfile.mkdtemp(prefix="jittest-demo-"))
    try:
        repo = build_repo(root)
        print(f"demo repository: {repo}")
        print("base commit: clamp present  |  head commit: clamp removed")
        rc = run_jittest(repo)
        print()
        print("The dry run uses a stub model, so what you saw is the pipeline's")
        print("targeting and oracle mechanics, for free. Re-run against your own")
        print("repository with a real key and without --dry-run for the full")
        print("generator + assessor path.")
        return rc
    finally:
        if keep:
            print(f"kept demo repository at: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
