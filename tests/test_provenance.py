"""Defects 33-35: an oracle verdict must name the two commits it is about.

"passes on base, fails on head" is the sentence the whole product rests on. It
is only meaningful if the two checkouts really contained base and head, and if
the candidate saw nothing but the revision under test.

Three failure modes are pinned here:

  * a caller hands in a directory that is not on the expected revision, so the
    verdict would silently describe some other pair of commits
  * a reused checkout carries residue from the previous candidate, so candidate
    N is judged in an environment candidate N-1 built
  * the verdict does not record which commits it examined, so the claim cannot
    be re-checked after the fact

Flakiness detection is also pinned, because the obvious fix for residue - clean
before every execution - would silently disable it.
"""
from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from jittest.execute import (
    RevisionMismatch,
    Worktree,
    differential_check,
    reset_workdir,
    resolve_revision,
    verify_workdir,
    worktree_revision,
)

from .helpers import CATCHING_TEST, FLAKY_TEST, FixtureRepo


class TestRevisionResolution(unittest.TestCase):
    def test_resolves_head_and_base_to_full_shas(self):
        with FixtureRepo() as repo:
            self.assertEqual(resolve_revision(repo.path, repo.base), repo.base)
            self.assertEqual(resolve_revision(repo.path, repo.head), repo.head)
            self.assertEqual(len(repo.head), 40)

    def test_unknown_revision_resolves_to_empty_string(self):
        with FixtureRepo() as repo:
            self.assertEqual(resolve_revision(repo.path, "deadbeef" * 5), "")

    def test_non_repository_resolves_to_empty_string(self):
        self.assertEqual(resolve_revision(Path("/"), "HEAD"), "")


class TestWorktreeProvenance(unittest.TestCase):
    def test_worktree_is_on_the_requested_commit(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.base) as work:
            self.assertEqual(worktree_revision(work), repo.base)
            verify_workdir(work, repo.base, "base")

    def test_wrong_revision_is_refused_not_reported(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            with self.assertRaises(RevisionMismatch):
                verify_workdir(work, repo.base, "base")

    def test_unknown_expected_sha_does_not_block(self):
        # An unresolvable expectation cannot be checked; it must not become a
        # false accusation against a valid checkout.
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            verify_workdir(work, "", "head")


class TestVerdictCarriesProvenance(unittest.TestCase):
    def test_catching_verdict_names_both_commits(self):
        with FixtureRepo() as repo:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2)
            self.assertTrue(v.is_catching)
            self.assertEqual(v.head_sha, repo.head)
            self.assertEqual(v.base_sha, repo.base)

    def test_mismatched_head_workdir_is_discarded(self):
        # The dangerous case: a reused directory that is on the wrong revision.
        # Previously this produced an ordinary verdict about the wrong commits.
        with FixtureRepo() as repo, Worktree(repo.path, repo.base) as wrong_dir:
            v = differential_check(repo.path, repo.base, repo.head,
                                   CATCHING_TEST, timeout_s=60, reruns=2,
                                   head_workdir=wrong_dir)
        self.assertFalse(v.is_catching)
        self.assertIn("provenance", v.reason)


class TestCandidateIsolation(unittest.TestCase):
    def test_reset_removes_untracked_residue_and_restores_tracked_files(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            residue = work / "left_behind_by_previous_candidate.py"
            residue.write_text("x = 1\n", encoding="utf-8")
            tracked = work / "calc.py"
            original = tracked.read_text(encoding="utf-8")
            tracked.write_text("raise SystemExit(1)\n", encoding="utf-8")

            reset_workdir(work)

            self.assertFalse(residue.exists(), "untracked residue survived")
            self.assertEqual(tracked.read_text(encoding="utf-8"), original,
                             "tracked file was not restored")
            self.assertEqual(worktree_revision(work), repo.head)

    def test_reset_removes_stale_bytecode(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            cache = work / "__pycache__"
            cache.mkdir(exist_ok=True)
            (cache / "calc.cpython-311.pyc").write_bytes(b"stale")
            reset_workdir(work)
            self.assertFalse(cache.exists())

    def test_reset_leaves_a_clean_checkout(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as work:
            reset_workdir(work)
            proc = subprocess.run(
                ["git", "-C", str(work), "status", "--porcelain"],
                capture_output=True, text=True,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stdout.strip(), "")

    def test_flakiness_is_still_detected_after_isolation_was_added(self):
        # Regression guard for the fix itself. Cleaning before every execution
        # rather than once per candidate destroys the state a flaky test uses,
        # which would convert "non-deterministic" into a confident verdict.
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as head_dir:
            v = differential_check(repo.path, repo.base, repo.head, FLAKY_TEST,
                                   timeout_s=60, reruns=2, head_workdir=head_dir)
        self.assertFalse(v.is_catching)
        self.assertIn("non-deterministic", v.reason)


if __name__ == "__main__":
    unittest.main()
