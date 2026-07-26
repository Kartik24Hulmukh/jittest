"""The most important tests in the repository.

They build a real throwaway git repository with a seeded behavioural
regression and assert that the differential oracle:

  - keeps a test that passes on base and fails on head
  - throws away a test that passes on head (a hardening test)
  - throws away a test that cannot be collected
  - throws away a test whose failure does not reproduce (flaky)

If these four ever go green wrongly, jittest is a noise generator and the
whole product claim collapses. Nothing here consults a model.
"""
from __future__ import annotations

import unittest

from jittest.execute import Outcome, Worktree, differential_check, run_test

from .helpers import (
    BROKEN_TEST,
    CATCHING_TEST,
    FLAKY_TEST,
    HARDENING_TEST,
    FixtureRepo,
)


class TestDifferentialOracle(unittest.TestCase):
    def test_catching_test_is_kept(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2)
        self.assertTrue(v.is_catching, v.reason)
        self.assertIn("passes on base", v.reason)
        self.assertTrue(v.failure_excerpt)

    def test_hardening_test_is_discarded(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   HARDENING_TEST, timeout_s=60, reruns=2)
        self.assertFalse(v.is_catching)
        self.assertIn("hardening", v.reason)

    def test_uncollectable_test_is_discarded(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   BROKEN_TEST, timeout_s=60, reruns=2)
        self.assertFalse(v.is_catching)
        self.assertIn("collect", v.reason)

    def test_flaky_test_is_discarded(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as head_dir:
            v = differential_check(repo.path, repo.base, repo.head, FLAKY_TEST,
                                   timeout_s=60, reruns=2, head_workdir=head_dir)
        self.assertFalse(v.is_catching)
        self.assertIn("non-deterministic", v.reason)


class TestRunTest(unittest.TestCase):
    def test_outcomes_and_cleanup(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            self.assertIs(run_test(work, CATCHING_TEST, 60).outcome, Outcome.FAIL)
            self.assertIs(run_test(work, HARDENING_TEST, 60).outcome, Outcome.PASS)
            self.assertIs(run_test(work, BROKEN_TEST, 60).outcome, Outcome.ERROR)
            leftovers = list(work.glob("test_jittest_candidate_*.py"))
            self.assertEqual(leftovers, [], "candidate files must be cleaned up")


if __name__ == "__main__":
    unittest.main()
