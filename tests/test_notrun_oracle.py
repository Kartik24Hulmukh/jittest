"""Defect 32: a runner exiting 0 is not evidence that a test passed.

pytest exits 0 when every collected test was SKIPPED, and the mini-runner did
the same for every fixture-using test. ``run_test`` mapped exit 0 to
``Outcome.PASS``, and ``differential_check`` accepts PASS on base as the
load-bearing half of "catching: passes on base, fails on head".

The consequence was a fabricated catch. A candidate that guards its import so
the file stays importable on a revision where the symbol does not exist yet
fails on head and "passes" on base while executing nothing at all on base. The
generator is told "(new code, no prior version)" in exactly that situation, so
this is a likely model output rather than an exotic one.

These tests exist to make that shape unrepresentable, and to prove the fix does
not achieve it by discarding genuine catches too.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jittest._minirunner import (
    EXIT_COLLECTION_ERROR,
    EXIT_FAILED,
    EXIT_NO_TESTS,
    EXIT_OK,
    run_file,
)
from jittest.execute import (
    Outcome,
    _passed_from_junit,
    differential_check,
    run_test,
)


def _write(body: str, stem: str) -> Path:
    directory = Path(tempfile.mkdtemp(prefix="jittest-notrun-"))
    path = directory / f"{stem}.py"
    path.write_text(body, encoding="utf-8")
    return path


class MiniRunnerExitCodes(unittest.TestCase):
    """Exit 0 must mean "a test ran and passed", never merely "no failures"."""

    def test_a_real_pass_is_zero(self) -> None:
        path = _write("def test_a():\n    assert True\n", "mr_pass")
        self.assertEqual(run_file(path), EXIT_OK)

    def test_a_real_failure_is_one(self) -> None:
        path = _write("def test_a():\n    assert False\n", "mr_fail")
        self.assertEqual(run_file(path), EXIT_FAILED)

    def test_no_tests_collected_is_five(self) -> None:
        path = _write("x = 1\n", "mr_empty")
        self.assertEqual(run_file(path), EXIT_NO_TESTS)

    def test_every_test_skipped_for_fixtures_is_not_success(self) -> None:
        # Fixtures now resolve (tmp_path is a built-in), so this test skips
        # explicitly instead. Skipping every test collected is not a pass.
        path = _write(
            "import unittest\n\n\ndef test_a(tmp_path):\n"
            "    raise unittest.SkipTest('not applicable here')\n",
            "mr_fixture",
        )
        self.assertEqual(run_file(path), EXIT_NO_TESTS)

    def test_skiptest_is_a_skip_and_not_a_pass_or_a_failure(self) -> None:
        path = _write(
            "import unittest\n\n\ndef test_a():\n"
            "    raise unittest.SkipTest('not applicable here')\n",
            "mr_skiptest",
        )
        self.assertEqual(run_file(path), EXIT_NO_TESTS)

    def test_one_genuine_pass_beside_a_skip_is_still_success(self) -> None:
        path = _write(
            "def test_a():\n    assert True\n\n\n"
            "def test_b(tmp_path):\n    assert True\n",
            "mr_mixed",
        )
        self.assertEqual(run_file(path), EXIT_OK)

    def test_an_uncollectable_file_is_two(self) -> None:
        path = _write("import nonexistent_module_xyz\n", "mr_broken")
        self.assertEqual(run_file(path), EXIT_COLLECTION_ERROR)


class JunitReader(unittest.TestCase):
    """The pytest path needs positive evidence, read from the junit report."""

    def _parse(self, xml: str) -> int | None:
        directory = Path(tempfile.mkdtemp(prefix="jittest-junit-"))
        report = directory / "report.xml"
        report.write_text(xml, encoding="utf-8")
        return _passed_from_junit(report)

    def test_a_single_passing_case_counts(self) -> None:
        self.assertEqual(
            self._parse(
                '<testsuites><testsuite tests="1">'
                '<testcase name="t"/></testsuite></testsuites>'
            ),
            1,
        )

    def test_all_skipped_counts_zero(self) -> None:
        self.assertEqual(
            self._parse(
                '<testsuites><testsuite tests="2">'
                '<testcase name="t1"><skipped message="m"/></testcase>'
                '<testcase name="t2"><skipped message="m"/></testcase>'
                "</testsuite></testsuites>"
            ),
            0,
        )

    def test_a_skip_does_not_hide_a_genuine_pass(self) -> None:
        self.assertEqual(
            self._parse(
                '<testsuites><testsuite tests="2">'
                '<testcase name="t1"><skipped/></testcase>'
                '<testcase name="t2"/></testsuite></testsuites>'
            ),
            1,
        )

    def test_failures_and_errors_do_not_count_as_passes(self) -> None:
        self.assertEqual(
            self._parse(
                '<testsuites><testsuite tests="2">'
                '<testcase name="t1"><failure message="m"/></testcase>'
                '<testcase name="t2"><error message="m"/></testcase>'
                "</testsuite></testsuites>"
            ),
            0,
        )

    def test_a_report_with_no_cases_counts_zero(self) -> None:
        self.assertEqual(
            self._parse('<testsuites><testsuite tests="0"/></testsuites>'), 0
        )

    def test_an_unparseable_report_is_unknown_not_a_pass(self) -> None:
        self.assertIsNone(self._parse("<not xml at all"))

    def test_a_missing_report_is_unknown_not_a_pass(self) -> None:
        directory = Path(tempfile.mkdtemp(prefix="jittest-junit-"))
        self.assertIsNone(_passed_from_junit(directory / "absent.xml"))


class _ForceMiniRunner(unittest.TestCase):
    """Base class: pin the runner so these tests do not depend on pytest."""

    def setUp(self) -> None:
        self._previous = os.environ.get("JITTEST_FORCE_MINIRUNNER")
        os.environ["JITTEST_FORCE_MINIRUNNER"] = "1"

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("JITTEST_FORCE_MINIRUNNER", None)
        else:
            os.environ["JITTEST_FORCE_MINIRUNNER"] = self._previous


class RunTestOutcomeMapping(_ForceMiniRunner):
    """run_test must not report PASS for a run that executed nothing."""

    def setUp(self) -> None:
        super().setUp()
        self.workdir = Path(tempfile.mkdtemp(prefix="jittest-workdir-"))

    def test_skipping_everything_is_notrun_not_pass(self) -> None:
        # tmp_path now resolves; the skip must be explicit to mean "not run".
        result = run_test(
            self.workdir,
            "import unittest\n\ndef test_a(tmp_path):\n"
            "    raise unittest.SkipTest('not applicable here')\n",
        )
        self.assertIs(result.outcome, Outcome.NOTRUN)

    def test_a_genuine_pass_is_still_pass(self) -> None:
        result = run_test(self.workdir, "def test_a():\n    assert True\n")
        self.assertIs(result.outcome, Outcome.PASS)

    def test_a_genuine_failure_is_still_fail(self) -> None:
        result = run_test(self.workdir, "def test_a():\n    assert False\n")
        self.assertIs(result.outcome, Outcome.FAIL)

    def test_the_candidate_file_is_always_removed(self) -> None:
        run_test(self.workdir, "def test_a():\n    assert True\n")
        leftovers = list(self.workdir.glob("test_jittest_candidate_*.py"))
        self.assertEqual(leftovers, [])

    def test_the_junit_report_is_always_removed(self) -> None:
        run_test(self.workdir, "def test_a():\n    assert True\n")
        leftovers = list(self.workdir.glob(".jittest-junit-*.xml"))
        self.assertEqual(leftovers, [])


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    return done.stdout.strip()


def _repo(base_source: str, head_source: str) -> tuple[Path, str, str]:
    root = Path(tempfile.mkdtemp(prefix="jittest-repo-"))
    _git("init", "--quiet", cwd=root)
    _git("config", "user.email", "tests@jittest.invalid", cwd=root)
    _git("config", "user.name", "jittest tests", cwd=root)
    (root / "mod.py").write_text(base_source, encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "--quiet", "-m", "base", cwd=root)
    base = _git("rev-parse", "HEAD", cwd=root)
    (root / "mod.py").write_text(head_source, encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "--quiet", "-m", "head", cwd=root)
    head = _git("rev-parse", "HEAD", cwd=root)
    return root, base, head


# A candidate of the shape a model actually produces for newly added code: the
# import is guarded so the module still imports on the revision that predates
# the symbol, and an unrelated fixture-using test sits alongside it. Both tests
# skip when calc is absent: the mini-runner resolves tmp_path now, so an
# unguarded fixture test would execute and pass on base even though nothing
# about calc was verified there.
GUARDED_CANDIDATE = """
import unittest

try:
    from mod import calc
except ImportError:
    calc = None


def _needs_calc():
    if calc is None:
        raise unittest.SkipTest("calc does not exist on this revision")


def test_calc_doubles():
    _needs_calc()
    assert calc(2) == 4


def test_environment_is_sane(tmp_path):
    _needs_calc()
    assert tmp_path is not None
"""

HONEST_CANDIDATE = """
from mod import calc


def test_calc_doubles():
    assert calc(2) == 4
"""


class DifferentialOracleEndToEnd(_ForceMiniRunner):
    """The whole point: no fabricated catches, and no lost genuine catches."""

    def test_a_test_that_never_ran_on_base_is_not_a_catch(self) -> None:
        # calc() does not exist on base at all, so nothing about it can have
        # been verified there.
        root, base, head = _repo(
            "def unrelated():\n    return 1\n",
            "def unrelated():\n    return 1\n\n\ndef calc(x):\n    return x * 3\n",
        )
        verdict = differential_check(root, base, head, GUARDED_CANDIDATE, reruns=2)
        self.assertFalse(verdict.is_catching)
        self.assertIs(verdict.base_outcome, Outcome.NOTRUN)
        self.assertIn("cannot be established", verdict.reason)

    def test_a_genuine_regression_is_still_caught(self) -> None:
        # calc() exists on both revisions, is correct on base, broken on head.
        root, base, head = _repo(
            "def calc(x):\n    return x * 2\n",
            "def calc(x):\n    return x * 3\n",
        )
        verdict = differential_check(root, base, head, HONEST_CANDIDATE, reruns=2)
        self.assertTrue(verdict.is_catching)
        self.assertIs(verdict.head_outcome, Outcome.FAIL)
        self.assertIs(verdict.base_outcome, Outcome.PASS)

    def test_a_hardening_test_is_still_discarded(self) -> None:
        root, base, head = _repo(
            "def calc(x):\n    return x * 2\n",
            "def calc(x):\n    return x * 2\n\n\ndef extra():\n    return 0\n",
        )
        verdict = differential_check(root, base, head, HONEST_CANDIDATE, reruns=2)
        self.assertFalse(verdict.is_catching)
        self.assertIs(verdict.head_outcome, Outcome.PASS)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
