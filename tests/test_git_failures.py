"""Defect 43: a failure to look must not be reported as having found nothing.

``git_diff`` returned ``""`` on every path that did not produce output,
including the paths where git itself failed. A mistyped revision, a shallow
clone that does not contain the base commit, a corrupt object store, or git
missing from PATH all produced the same result as two identical commits: an
empty diff, zero targets, zero candidates, zero model calls, and a report that
exited successfully saying "no changed Python symbols were found".

That is the same family of defect as the eval harness deciding a bug had been
measured from a stopwatch. The system was not wrong about an answer; it was
presenting the absence of an answer as an answer. In an evaluation run these
unmeasured pairs are averaged into the denominator as misses, which understates
the catch rate with numbers that were never observed.

An empty diff is a fact about the revision pair. A git failure is the absence
of a fact. These tests pin the difference at both layers.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest.config import Config
from jittest.diff import GitError, git_diff
from jittest.llm import DryRunLLM
from jittest.pipeline import run

from .helpers import FixtureRepo


def _cfg() -> Config:
    return Config(risk_threshold=0.0, max_targets=1, candidates_per_target=1,
                  timeout_s=60, reruns=2, ledger_path=".jittest/test-git.db")


class TestGitDiffDistinguishesFailureFromEmptiness(unittest.TestCase):
    def test_a_nonexistent_revision_raises_instead_of_returning_empty(self):
        # The single most likely real-world trigger: a branch that was deleted,
        # or a base SHA that is not present in a shallow CI checkout.
        with FixtureRepo() as repo, self.assertRaises(GitError) as caught:
            git_diff(repo.path, "0" * 40, repo.head)
        self.assertIn("failure to measure", str(caught.exception))

    def test_the_error_says_what_git_actually_reported(self):
        # A diagnosis the operator cannot act on is barely better than silence,
        # so git's own stderr has to survive into the message.
        with FixtureRepo() as repo, self.assertRaises(GitError) as caught:
            git_diff(repo.path, "no-such-ref", repo.head)
        message = str(caught.exception)
        self.assertIn("no-such-ref", message)
        self.assertIn("exited", message)

    def test_a_directory_that_is_not_a_repository_raises(self):
        with tempfile.TemporaryDirectory() as td, self.assertRaises(GitError):
            git_diff(Path(td), "HEAD~1", "HEAD")

    def test_identical_revisions_are_still_empty_not_an_error(self):
        # The other half of the property. Over-raising would turn a legitimate
        # "nothing changed" into a spurious failure, which is its own lie.
        with FixtureRepo() as repo:
            self.assertEqual(git_diff(repo.path, repo.head, repo.head), "")

    def test_a_real_pair_still_produces_a_diff(self):
        with FixtureRepo() as repo:
            self.assertIn("calc.py", git_diff(repo.path, repo.base, repo.head))

    def test_the_error_never_claims_the_code_was_unchanged(self):
        # The wording matters as much as the exception. The old message was
        # quoted into PR comments and read as a verdict about the code.
        with FixtureRepo() as repo, self.assertRaises(GitError) as caught:
            git_diff(repo.path, "0" * 40, repo.head)
        self.assertNotIn("no changed Python symbols", str(caught.exception))


class TestPipelineReportsWhyItStopped(unittest.TestCase):
    def test_git_failure_is_labelled_git_failed(self):
        with FixtureRepo() as repo:
            report = run(repo.path, "0" * 40, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.diff_status, "git_failed")

    def test_git_failure_is_not_labelled_empty(self):
        # The distinction only pays off if a consumer can act on it: an eval
        # harness must be able to exclude this run from its denominator rather
        # than score it as a miss.
        with FixtureRepo() as repo:
            report = run(repo.path, "0" * 40, repo.head, _cfg(), DryRunLLM())
        self.assertNotEqual(report.diff_status, "empty")
        self.assertTrue(report.errors)
        joined = " ".join(report.errors)
        self.assertNotIn("property of the revision pair", joined)

    def test_an_identical_pair_is_labelled_empty(self):
        with FixtureRepo() as repo:
            report = run(repo.path, repo.head, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.diff_status, "empty")

    def test_a_normal_run_is_labelled_ok(self):
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.diff_status, "ok")

    def test_git_failure_does_not_call_the_model(self):
        # Nothing was examined, so a request would be pure cost - and a nonzero
        # model_requests would make the run look measured to assert_measured.
        with FixtureRepo() as repo:
            report = run(repo.path, "0" * 40, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.model_requests, 0)

    def test_the_status_survives_serialisation(self):
        # The artifact is the only thing a reviewer sees days later.
        with FixtureRepo() as repo:
            report = run(repo.path, "0" * 40, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.as_dict().get("diff_status"), "git_failed")

    def test_git_failure_reports_no_findings(self):
        with FixtureRepo() as repo:
            report = run(repo.path, "0" * 40, repo.head, _cfg(), DryRunLLM())
        self.assertEqual(report.findings, [])
        self.assertFalse(report.has_regression)


class TestGitFailureIsReachableInPractice(unittest.TestCase):
    def test_a_shallow_clone_missing_the_base_commit_fails_loudly(self):
        """The realistic CI shape, not a synthetic bad SHA.

        `actions/checkout` defaults to depth 1. A workflow that compares
        against a base commit outside that depth gets a real object-store miss,
        which is precisely the case that used to report "no changes".
        """
        with FixtureRepo() as repo, tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "shallow"
            cloned = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1",
                 f"file://{repo.path}", str(dest)],
                capture_output=True, text=True,
            )
            if cloned.returncode != 0:
                self.skipTest("git could not create a shallow file:// clone here")
            has_base = subprocess.run(
                ["git", "-C", str(dest), "cat-file", "-e", f"{repo.base}^{{commit}}"],
                capture_output=True, text=True,
            )
            if has_base.returncode == 0:
                self.skipTest("clone was not actually shallow")
            with self.assertRaises(GitError):
                git_diff(dest, repo.base, "HEAD")


if __name__ == "__main__":
    unittest.main()
