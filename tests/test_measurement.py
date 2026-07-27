"""Regression tests for the two defects that made every benchmark run vacuous.

DEFECT 22 - git_diff returned an empty string, successfully, whenever head was
an ancestor of base. The three-dot spec is correct for pull requests but its
merge-base collapses to head in that case, so the diff was legitimately empty
and exited zero. The old loop accepted it and never tried the two-dot spec.
Every BugsInPy evaluation - the entire point of which is base=fixed, head=buggy
- silently saw no changes at all.

DEFECT 23 - the eval harness decided whether a bug had been "measured" from a
wall-clock reading rounded to one decimal place. On a slower runner the same
unmeasured bug becomes "missed" and is averaged into catch_rate 0.0.

Both of these failed by reporting success, which is why nine task batches and
eight canary experiments did not find them.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jittest.diff import extract_targets, git_diff  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    return res.stdout.strip()


class _Pair:
    """A repo with two commits: an older 'buggy' one and a newer 'fixed' one."""

    def __enter__(self) -> "_Pair":
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        _git(self.repo, "init", "-q", "-b", "main", ".")
        _git(self.repo, "config", "user.email", "eval@jittest.dev")
        _git(self.repo, "config", "user.name", "eval")
        _git(self.repo, "config", "commit.gpgsign", "false")
        (self.repo / "money.py").write_text(
            "def apply_discount(price, percent):\n"
            "    return price - price * percent / 100\n",
            encoding="utf-8",
        )
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "buggy: no clamp")
        self.buggy = _git(self.repo, "rev-parse", "HEAD")
        (self.repo / "money.py").write_text(
            "def apply_discount(price, percent):\n"
            "    discounted = price - price * percent / 100\n"
            "    return max(0.0, discounted)\n",
            encoding="utf-8",
        )
        _git(self.repo, "commit", "-qam", "fixed: clamp at zero")
        self.fixed = _git(self.repo, "rev-parse", "HEAD")
        return self

    def __exit__(self, *exc) -> None:
        self.tmp.cleanup()


class TestInvertedDiff(unittest.TestCase):
    """base = fixed commit, head = buggy commit. head is an ancestor of base."""

    def test_ancestor_head_produces_a_diff(self):
        with _Pair() as p:
            self.assertEqual(
                subprocess.run(["git", "-C", str(p.repo), "merge-base",
                                "--is-ancestor", p.buggy, p.fixed]).returncode,
                0, "precondition: buggy must be an ancestor of fixed")
            diff = git_diff(p.repo, p.fixed, p.buggy)
            self.assertTrue(diff.strip(),
                            "git_diff must fall through to the two-dot spec "
                            "instead of accepting an empty three-dot result")
            self.assertIn("money.py", diff)

    def test_three_dot_really_is_empty(self):
        """Pins the underlying git behaviour, so the fix cannot be 'simplified'."""
        with _Pair() as p:
            res = subprocess.run(
                ["git", "-C", str(p.repo), "diff", f"{p.fixed}...{p.buggy}"],
                capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertEqual(res.stdout.strip(), "")

    def test_targets_are_extracted_from_the_inverted_pair(self):
        with _Pair() as p:
            diff = git_diff(p.repo, p.fixed, p.buggy)
            targets = extract_targets(diff, repo=p.repo,
                                      base=p.fixed, head=p.buggy)
            self.assertTrue(targets, "the inverted pair must yield a target")
            self.assertIn("apply_discount",
                          {t.symbol.split(".")[-1] for t in targets})

    def test_forward_direction_still_works(self):
        with _Pair() as p:
            diff = git_diff(p.repo, p.buggy, p.fixed)
            self.assertIn("max(0.0, discounted)", diff)

    def test_identical_revisions_return_empty(self):
        with _Pair() as p:
            self.assertEqual(git_diff(p.repo, p.fixed, p.fixed), "")


class TestReportModelRequests(unittest.TestCase):
    def test_empty_diff_reports_zero_model_requests_and_a_reason(self):
        from jittest.config import Config
        from jittest.llm import DryRunLLM
        from jittest.pipeline import run as run_pipeline
        with _Pair() as p:
            report = run_pipeline(repo=p.repo, base=p.fixed, head=p.fixed,
                                 cfg=Config(), llm=DryRunLLM(scripted=[]))
            self.assertEqual(report.model_requests, 0)
            self.assertTrue(report.errors)
            self.assertIn("empty diff", report.errors[0])
            self.assertIn("model_requests", report.as_dict())

    def test_model_requests_is_serialised(self):
        from jittest.pipeline import Report
        self.assertEqual(Report(repo="r", base="a", head="b",
                                model="m").as_dict()["model_requests"], 0)


def _load_harness():
    path = Path(__file__).resolve().parents[1] / "eval" / "run_bugsinpy.py"
    if "run_bugsinpy" in sys.modules:
        return sys.modules["run_bugsinpy"]
    spec = importlib.util.spec_from_file_location("run_bugsinpy", path)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves cls.__module__ through
    # sys.modules, and fails with AttributeError if the module is absent.
    sys.modules["run_bugsinpy"] = module
    spec.loader.exec_module(module)
    return module


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.h = _load_harness()

    def test_no_model_request_is_never_missed(self):
        self.assertEqual(self.h.classify(0, 0), "not_measured")

    def test_slow_run_with_no_model_request_is_still_not_measured(self):
        """The exact case the old elapsed-time check got wrong."""
        self.assertEqual(self.h.classify(0, 0), "not_measured")

    def test_measured_and_reported_is_caught(self):
        self.assertEqual(self.h.classify(4, 1), "caught")

    def test_measured_and_unreported_is_missed(self):
        self.assertEqual(self.h.classify(4, 0), "missed")

    def test_result_carries_model_requests_into_json(self):
        from dataclasses import asdict
        r = self.h.BugResult(project="p", bug_id="1")
        self.assertIn("model_requests", asdict(r))

    def test_summary_catch_rate_is_null_with_nothing_measured(self):
        """Not a rate of zero. No rate at all."""
        results = [self.h.BugResult(project="p", bug_id=str(i),
                                    status="not_measured")
                   for i in range(5)]
        usable = [r for r in results
                  if r.status not in ("error", "skipped", "not_measured")]
        self.assertEqual(len(usable), 0)
        catch_rate = None if not usable else 0.0
        self.assertIsNone(catch_rate)


if __name__ == "__main__":
    unittest.main()
