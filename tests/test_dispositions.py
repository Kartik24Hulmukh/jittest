"""Defects 36-40: a verdict must state what happened, not describe it.

The pipeline used to recover a candidate's disposition by searching the
verdict's English reason string for substrings. Two consequences:

  * rewording a sentence silently relabelled telemetry, so the labels a user
    trusts were coupled to prose nobody treated as an interface
  * every ending that no substring distinguished fell through to
    "head_failed_base_failed_latent" - including "no test executed on base" and
    a revision-provenance mismatch, which are not that, and are worse

These tests pin the typed vocabulary, the per-execution record, and the
separation of an assertion that fired from a crash or a runner problem.
"""
from __future__ import annotations

import unittest

from jittest.execute import (
    Disposition,
    FailureKind,
    Outcome,
    Verdict,
    Worktree,
    differential_check,
    run_test,
)
from jittest.pipeline import DISPOSITIONS, _disposition_from_verdict

from .helpers import (
    BROKEN_TEST,
    CATCHING_TEST,
    FLAKY_TEST,
    HARDENING_TEST,
    FixtureRepo,
)


class TestDispositionVocabulary(unittest.TestCase):
    def test_every_oracle_disposition_is_a_known_telemetry_value(self):
        for d in Disposition:
            self.assertIn(d.value, DISPOSITIONS)

    def test_vocabulary_has_no_duplicates(self):
        self.assertEqual(len(DISPOSITIONS), len(set(DISPOSITIONS)))

    def test_pre_oracle_dispositions_are_still_present(self):
        for value in ("model_declined", "parse_failed", "safety_rejected", "rate_limited", "timed_out"):
            self.assertIn(value, DISPOSITIONS)

    def test_endings_that_used_to_collapse_are_now_distinct(self):
        # The whole point of Defect 38. Before, all of these were reported as
        # "fails on base too, pre-existing", which is a far milder claim.
        distinct = {
            Disposition.HEAD_FAILED_BASE_FAILED_LATENT,
            Disposition.BASE_NOTRUN,
            Disposition.BASE_UNCOLLECTABLE,
            Disposition.PROVENANCE_FAILED,
            Disposition.HEAD_TIMEOUT,
            Disposition.HEAD_NOTRUN,
        }
        self.assertEqual(len(distinct), 6)


class TestDispositionIsStatedNotParsed(unittest.TestCase):
    def test_reason_rewording_cannot_change_the_disposition(self):
        # Previously this verdict would have been mislabelled purely because of
        # the words in its reason string.
        v = Verdict(False, "discarded: fails on base too, pre-existing",
                    disposition=Disposition.BASE_NOTRUN)
        self.assertEqual(_disposition_from_verdict(v), "base_notrun")

    def test_prose_free_reason_still_yields_a_disposition(self):
        v = Verdict(False, "", disposition=Disposition.HEAD_TIMEOUT)
        self.assertEqual(_disposition_from_verdict(v), "head_timeout")


class TestObservedDispositions(unittest.TestCase):
    def test_catching(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2)
        self.assertEqual(v.disposition, Disposition.CATCHING)
        self.assertEqual(_disposition_from_verdict(v), "catching")

    def test_hardening(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   HARDENING_TEST, timeout_s=60, reruns=2)
        self.assertEqual(v.disposition, Disposition.HEAD_PASSED)

    def test_uncollectable(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   BROKEN_TEST, timeout_s=60, reruns=2)
        self.assertEqual(v.disposition, Disposition.HEAD_UNCOLLECTABLE)

    def test_flaky(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as head_dir:
            v = differential_check(repo.path, repo.base, repo.head, FLAKY_TEST,
                                   timeout_s=60, reruns=2, head_workdir=head_dir)
        self.assertEqual(v.disposition, Disposition.HEAD_FLAKY)

    def test_provenance_mismatch_is_not_reported_as_latent(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.base) as wrong_dir:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2,
                                   head_workdir=wrong_dir)
        self.assertEqual(v.disposition, Disposition.PROVENANCE_FAILED)
        self.assertNotEqual(v.disposition,
                            Disposition.HEAD_FAILED_BASE_FAILED_LATENT)


class TestExecutionRecord(unittest.TestCase):
    def test_catching_verdict_records_every_execution(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2)
        # Two head executions (first plus one rerun) and one base execution.
        self.assertEqual(v.head_run_count, 2)
        self.assertEqual(v.base_run_count, 1)
        self.assertEqual(list(v.head_runs), [Outcome.FAIL, Outcome.FAIL])
        self.assertEqual(list(v.base_runs), [Outcome.PASS])
        self.assertTrue(v.rerun_agreement)

    def test_flaky_verdict_records_disagreeing_outcomes(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as head_dir:
            v = differential_check(repo.path, repo.base, repo.head, FLAKY_TEST,
                                   timeout_s=60, reruns=2, head_workdir=head_dir)
        self.assertGreater(v.head_run_count, 1)
        self.assertGreater(len(set(v.head_runs)), 1)
        self.assertFalse(v.rerun_agreement)
        # Nothing was executed on base, and the record says so rather than
        # leaving a reader to assume a comparison happened.
        self.assertEqual(v.base_run_count, 0)

    def test_every_ending_records_the_run_that_produced_it(self):
        """A verdict that executed something must say so.

        Found by running the oracle against a real repository rather than
        against fixtures. The head_notrun and head_passed endings return before
        the rerun loop, and nothing asserted their run record - so if either
        stopped recording, the two most common outcomes in practice would both
        report zero executions while CI stayed green.
        """
        with FixtureRepo() as repo:
            passed = differential_check(repo.path, repo.base, repo.head,
                                        HARDENING_TEST, timeout_s=60, reruns=2)
        self.assertEqual(passed.head_run_count, 1)
        self.assertEqual(list(passed.head_runs), [Outcome.PASS])

        with FixtureRepo() as repo:
            broken = differential_check(repo.path, repo.base, repo.head,
                                        BROKEN_TEST, timeout_s=60, reruns=2)
        self.assertEqual(broken.head_run_count, 1)

    def test_no_verdict_claims_zero_runs_after_executing(self):
        with FixtureRepo() as repo:
            for code in (CATCHING_TEST, HARDENING_TEST, BROKEN_TEST):
                v = differential_check(repo.path, repo.base, repo.head, code,
                                       timeout_s=60, reruns=2)
                with self.subTest(disposition=str(v.disposition)):
                    self.assertGreater(
                        v.head_run_count, 0,
                        f"{v.disposition} reported no head execution")

    def test_hardening_verdict_never_touched_base(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   HARDENING_TEST, timeout_s=60, reruns=2)
        self.assertEqual(v.base_run_count, 0)


class TestFailureKind(unittest.TestCase):
    def test_assertion_failure_is_distinguished_from_a_crash(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            fired = run_test(work, CATCHING_TEST, timeout_s=60)
            self.assertIs(fired.outcome, Outcome.FAIL)
            self.assertEqual(fired.failure_kind, FailureKind.ASSERTION)

    def test_uncollectable_candidate_is_an_error_not_an_assertion(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            broken = run_test(work, BROKEN_TEST, timeout_s=60)
        self.assertIn(broken.outcome, (Outcome.ERROR, Outcome.FAIL))
        self.assertNotEqual(broken.failure_kind, FailureKind.ASSERTION)

    def test_a_passing_run_has_no_failure_kind(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            ok = run_test(work, HARDENING_TEST, timeout_s=60)
        self.assertIs(ok.outcome, Outcome.PASS)
        self.assertEqual(ok.failure_kind, FailureKind.NONE)


if __name__ == "__main__":
    unittest.main()
