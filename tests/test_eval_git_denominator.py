"""Truth tests for git-failure handling in the eval catch-rate denominator.

Loop 7 made the pipeline SAY when git failed (Report.diff_status). This loop
makes the eval harness LISTEN.

A git failure means the revision pair could not be compared, so the bug was
never presented to the tool. It is not a miss - the tool did not fail to
catch anything. And it must not silently vanish either (Defect 48: a
denominator that quietly deletes failures is how one success beside four
broken checkouts once read as 100%). So a git-failed run is disclosed by
name, counted, and excluded from the headline denominator, while the
conservative all-attempted rate is printed right beside it.

Every assertion here corresponds to a number that would be published.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bugs = load("eval_denom_bugs", "eval/run_bugsinpy.py")
gate = load("eval_denom_gate", "eval/assert_measured.py")


class TestClassifySeparatesGitFailure(unittest.TestCase):
    """classify() gains a diff_status argument; git_failed is its own status."""

    def test_git_failure_is_its_own_status(self):
        self.assertEqual(bugs.classify(0, 0, "git_failed"), "git_failed")

    def test_diff_status_wins_over_the_request_count(self):
        # Defensive: if the pipeline says git failed, no number of requests
        # turns the run into a measurement of the tool.
        self.assertEqual(bugs.classify(5, 2, "git_failed"), "git_failed")

    def test_empty_diff_stays_not_measured(self):
        # An empty diff is a property of the revision pair: the tool looked
        # and there was nothing to aim at. That stays in the denominator.
        self.assertEqual(bugs.classify(0, 0, "empty"), "not_measured")

    def test_default_argument_preserves_existing_callers(self):
        self.assertEqual(bugs.classify(0, 0), "not_measured")
        self.assertEqual(bugs.classify(2, 1), "caught")
        self.assertEqual(bugs.classify(2, 0), "missed")


class TestGitFailureLeavesTheDenominatorOpenly(unittest.TestCase):
    def test_git_failed_is_counted_named_and_excluded(self):
        rows = [
            bugs.BugResult("p", "1", status="caught",
                           catching_candidates=1, model_requests=3),
            bugs.BugResult("p", "2", status="missed", model_requests=3),
            bugs.BugResult("p", "3", status="git_failed",
                           error="git could not compare these revisions"),
        ]
        summary = bugs.summarize(rows)
        self.assertEqual(summary["bugs_attempted"], 3)
        self.assertEqual(summary["bugs_git_failed"], 1)
        self.assertEqual(summary["bugs_eligible"], 2)
        self.assertEqual(summary["bugs_measured"], 2)
        # The headline is over bugs the tool was actually presented with.
        self.assertEqual(summary["catch_rate"], 0.5)
        # The conservative floor is printed right beside it, so a reader can
        # always reconstruct the harsher number.
        self.assertEqual(summary["catch_rate_all_attempted"], round(1 / 3, 3))

    def test_all_git_failed_withholds_the_rate(self):
        rows = [bugs.BugResult("p", str(i), status="git_failed")
                for i in range(3)]
        summary = bugs.summarize(rows)
        self.assertEqual(summary["bugs_eligible"], 0)
        self.assertIsNone(summary["catch_rate"])
        self.assertEqual(summary["catch_rate_all_attempted"], 0.0)

    def test_no_git_failures_preserves_the_existing_arithmetic(self):
        rows = [bugs.BugResult("p", "1", status="caught",
                               catching_candidates=1, model_requests=2)]
        rows += [bugs.BugResult("p", str(i), status="error")
                 for i in range(2, 6)]
        summary = bugs.summarize(rows)
        self.assertEqual(summary["bugs_git_failed"], 0)
        self.assertEqual(summary["bugs_eligible"], 5)
        self.assertEqual(summary["catch_rate"], 0.2)
        self.assertEqual(summary["catch_rate_all_attempted"], 0.2)

    def test_empty_run_still_withholds_every_rate(self):
        summary = bugs.summarize([])
        self.assertIsNone(summary["catch_rate"])
        self.assertIsNone(summary["catch_rate_all_attempted"])
        self.assertEqual(summary["bugs_eligible"], 0)


class TestGateSeesGitFailures(unittest.TestCase):
    """The fail-closed gate cross-checks the new status instead of trusting it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jittest-gate-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, rows, summary=None) -> Path:
        payload = {
            "summary": summary if summary is not None else bugs.summarize(rows),
            "results": [asdict(r) for r in rows],
        }
        path = self.tmp / "results.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _run_gate(self, path: Path):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate.main(["assert_measured.py", str(path)])
        return code, out.getvalue(), err.getvalue()

    def _healthy_rows(self):
        rows = [
            bugs.BugResult("p", "1", status="caught",
                           catching_candidates=1, model_requests=4,
                           cost_usd=0.4),
            bugs.BugResult("p", "2", status="caught",
                           catching_candidates=2, model_requests=4,
                           cost_usd=0.4),
        ]
        rows += [bugs.BugResult("p", str(i), status="missed",
                                model_requests=4, cost_usd=0.4)
                 for i in range(3, 9)]
        rows += [bugs.BugResult("p", str(i), status="git_failed",
                                error="git could not compare these revisions")
                 for i in range(9, 11)]
        return rows

    def test_a_run_with_some_git_failures_can_still_pass(self):
        # 8 of 10 measured -> completion 0.8, exactly at the evidence floor.
        code, out, err = self._run_gate(self._write(self._healthy_rows()))
        self.assertEqual(code, 0, err)

    def test_systemic_git_failure_fails_the_gate(self):
        # 6 of 10 git-failed -> completion 0.4: the collection infrastructure
        # was broken, so no rate from this run means anything.
        rows = [bugs.BugResult("p", str(i), status="missed",
                               model_requests=4, cost_usd=0.4)
                for i in range(4)]
        rows += [bugs.BugResult("p", str(i + 4), status="git_failed",
                                error="git could not compare these revisions")
                 for i in range(6)]
        code, out, err = self._run_gate(self._write(rows))
        self.assertEqual(code, 1)
        self.assertIn("evidence floor", err)

    def test_the_gate_recomputes_the_git_failed_count(self):
        rows = self._healthy_rows()
        summary = bugs.summarize(rows)
        summary["bugs_git_failed"] = 0  # the harness lies; the rows do not
        code, out, err = self._run_gate(self._write(rows, summary=summary))
        self.assertEqual(code, 1)
        self.assertIn("bugs_git_failed", err)
        self.assertIn("disagrees", err)

    def test_a_missing_git_failed_key_fails_closed(self):
        rows = self._healthy_rows()
        summary = bugs.summarize(rows)
        del summary["bugs_git_failed"]
        code, out, err = self._run_gate(self._write(rows, summary=summary))
        self.assertEqual(code, 1)
        self.assertIn("bugs_git_failed", err)

    def test_git_failed_reasons_are_printed(self):
        code, out, err = self._run_gate(self._write(self._healthy_rows()))
        self.assertIn("git_failed reason", err)
        self.assertIn("git could not compare", err)


class TestEvaluateOneReportsGitFailure(unittest.TestCase):
    """Integration: a bogus revision pair flows through as git_failed."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="jittest-eval-git-test-"))
        self._git("init", "--quiet", "-b", "main")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n",
                                           encoding="utf-8")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "base")
        # The fail-fast guard errors out when a key is present with --dry-run.
        # This test is about git, not the guard, so the key is removed.
        self._saved_key = os.environ.pop("JITTEST_API_KEY", None)

    def tearDown(self):
        if self._saved_key is not None:
            os.environ["JITTEST_API_KEY"] = self._saved_key
        shutil.rmtree(self.repo, ignore_errors=True)

    def _git(self, *args: str):
        return subprocess.run(
            ["git", "-C", str(self.repo),
             "-c", "user.email=tests@jittest.dev",
             "-c", "user.name=jittest tests",
             "-c", "commit.gpgsign=false",
             *args],
            capture_output=True, text=True, check=True,
        )

    def test_bogus_revisions_produce_git_failed_not_error_not_miss(self):
        spec = bugs.BugSpec(
            project="test_project", bug_id="9",
            repo_url="file://" + str(self.repo),
            buggy_commit="0" * 40,
            fixed_commit="1" * 40,
        )
        result = bugs.evaluate_one(spec, self.repo, model="dry-run",
                                   budget=1.0, dry_run=True)
        self.assertEqual(result.status, "git_failed")
        self.assertEqual(result.model_requests, 0)
        self.assertIn("git could not compare", result.error)


if __name__ == "__main__":
    unittest.main()
