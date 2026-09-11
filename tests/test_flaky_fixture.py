"""Real subprocess regression coverage for the oracle's alternating fixture."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jittest.execute import Disposition, Outcome, Worktree, differential_check, run_test
from jittest.safety import check_candidate

from .helpers import _FLAKY_SCRATCH, FLAKY_TEST, FixtureRepo


class TestFlakyFixture(unittest.TestCase):
    def test_candidate_is_safe_without_reopening_n13(self):
        self.assertTrue(check_candidate(FLAKY_TEST).ok)
        unsafe = 'def test_write():\n    path = "foo" + "bar"\n    with open(path, "w") as fh:\n        fh.write("bad")\n    assert path\n'
        self.assertFalse(check_candidate(unsafe).ok)

    def test_same_basename_checkouts_are_isolated_and_repeatable(self):
        with tempfile.TemporaryDirectory() as root:
            checkouts = [Path(root) / arm / "checkout" for arm in ("first", "second")]
            for work in checkouts:
                work.mkdir(parents=True)
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    for expected in (Outcome.FAIL, Outcome.PASS, Outcome.FAIL, Outcome.PASS):
                        results = list(pool.map(lambda work: run_test(work, FLAKY_TEST, 60), checkouts))
                        self.assertEqual([r.outcome for r in results], [expected, expected])
                for work in checkouts:
                    self.assertFalse(list(work.glob(".flaky*")))
                    key = hashlib.sha256(os.fsencode(os.path.realpath(work))).hexdigest()
                    self.assertEqual((Path(_FLAKY_SCRATCH.name) / key).read_text(), "0")
            finally:
                for work in checkouts:
                    key = hashlib.sha256(os.fsencode(os.path.realpath(work))).hexdigest()
                    (Path(_FLAKY_SCRATCH.name) / key).unlink(missing_ok=True)

    def test_repeated_oracle_calls_on_reused_worktree(self):
        with FixtureRepo() as repo, Worktree(repo.path, repo.head) as head:
            for _ in range(2):
                verdict = differential_check(repo.path, repo.base, repo.head, FLAKY_TEST,
                                             timeout_s=60, reruns=2, head_workdir=head)
                self.assertIs(verdict.disposition, Disposition.HEAD_FLAKY)
                self.assertEqual(verdict.head_runs, (Outcome.FAIL, Outcome.PASS))

    def test_parent_process_cleans_scratch_directory(self):
        completed = subprocess.run(
            [sys.executable, "-c",
             "from tests.helpers import _FLAKY_SCRATCH; print(_FLAKY_SCRATCH.name)"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, check=True, timeout=30,
        )
        scratch = Path(completed.stdout.strip())
        self.assertTrue(scratch.name.startswith("jittest-flaky-"))
        self.assertFalse(scratch.exists(), "parent process must remove its scratch directory")
