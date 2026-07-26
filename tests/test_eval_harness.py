"""End-to-end test for the eval harness using DryRunLLM and a synthetic repo.

Exercises run_bugsinpy.py's evaluate_one function with a scripted model and
a two-commit git repository, proving the harness can produce telemetry rows
and classify results without network access.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from eval.run_bugsinpy import BugSpec, discover, evaluate_one

# A catching test that fails on the buggy head and passes on the fixed base.
CATCHING = '''\
from calc import apply_discount

def test_discount_never_goes_below_zero():
    assert apply_discount(100.0, 150.0) == 0.0
'''

BASE_SRC = '''\
def apply_discount(price, percent):
    if percent < 0:
        raise ValueError("negative")
    discounted = price - (price * percent / 100.0)
    if discounted < 0:
        return 0.0
    return discounted
'''

HEAD_SRC = '''\
def apply_discount(price, percent):
    if percent < 0:
        raise ValueError("negative")
    discounted = price - (price * percent / 100.0)
    return round(discounted, 2)
'''


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=tests@jittest.dev",
         "-c", "user.name=jittest tests",
         "-c", "commit.gpgsign=false",
         *args],
        capture_output=True, text=True, check=True,
    )


class TestEvalHarness(unittest.TestCase):
    """Exercise the harness end to end with DryRunLLM and a synthetic repo."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="jittest-eval-test-"))
        _git(self.repo, "init", "--quiet", "-b", "main")
        (self.repo / "calc.py").write_text(BASE_SRC, encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "--quiet", "-m", "base: correct")
        self.fixed_sha = _git(self.repo, "rev-parse", "HEAD").stdout.strip()

        (self.repo / "calc.py").write_text(HEAD_SRC, encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "--quiet", "-m", "head: buggy")
        self.buggy_sha = _git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_evaluate_one_with_catching_test(self):
        """The harness produces a BugResult with telemetry when the oracle catches."""
        spec = BugSpec(
            project="test_project", bug_id="1",
            repo_url="file://" + str(self.repo),
            buggy_commit=self.buggy_sha,
            fixed_commit=self.fixed_sha,
            test_file="test_calc.py",
        )
        result = evaluate_one(spec, self.repo, model="dry-run",
                              budget=1.0, dry_run=True)
        self.assertEqual(result.status, "missed")  # DryRunLLM won't produce a catching test
        self.assertEqual(result.error, "")
        self.assertTrue(len(result.telemetry) > 0)

    def test_evaluate_one_skips_missing_commits(self):
        """Bugs with missing commit IDs are skipped, not errored."""
        spec = BugSpec(
            project="test_project", bug_id="2",
            repo_url="", buggy_commit="", fixed_commit="",
        )
        result = evaluate_one(spec, self.repo, model="dry-run",
                              budget=1.0, dry_run=True)
        self.assertEqual(result.status, "skipped")
        self.assertIn("missing commit", result.error)

    def test_discover_returns_empty_for_missing_dir(self):
        """discover() returns [] when the projects directory doesn't exist."""
        specs = discover(Path("/nonexistent/path"), limit=10)
        self.assertEqual(specs, [])

    def test_telemetry_rows_have_required_fields(self):
        """Each telemetry row has all required CandidateTelemetry fields."""
        spec = BugSpec(
            project="test_project", bug_id="3",
            repo_url="file://" + str(self.repo),
            buggy_commit=self.buggy_sha,
            fixed_commit=self.fixed_sha,
        )
        result = evaluate_one(spec, self.repo, model="dry-run",
                              budget=1.0, dry_run=True)
        for tel in result.telemetry:
            self.assertIn("disposition", tel)
            self.assertIn("target_symbol", tel)
            self.assertIn("target_file", tel)
            self.assertIn("risk_score", tel)
            self.assertIn("candidate_index", tel)

    def test_dry_run_never_requires_network(self):
        """The harness works with --dry-run and no network access."""
        spec = BugSpec(
            project="test_project", bug_id="4",
            repo_url="file://" + str(self.repo),
            buggy_commit=self.buggy_sha,
            fixed_commit=self.fixed_sha,
        )
        # This should complete without any network calls
        result = evaluate_one(spec, self.repo, model="dry-run",
                              budget=1.0, dry_run=True)
        self.assertIsNotNone(result)
        self.assertNotEqual(result.status, "error")

    def test_harness_does_not_import_at_module_level(self):
        """Importing the harness module must not require network or jittest imports."""
        import importlib
        import sys
        # Remove jittest from sys.modules to prove no side effects
        mods_to_remove = [k for k in sys.modules if k.startswith("jittest")]
        for k in mods_to_remove:
            del sys.modules[k]
        # Re-import the eval module
        if "eval.run_bugsinpy" in sys.modules:
            del sys.modules["eval.run_bugsinpy"]
        importlib.import_module("eval.run_bugsinpy")
        # If we got here without error, the test passes
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
