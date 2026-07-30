"""Roadmap P3-2, end to end: marks, built-ins, and the adoption scenario.

Companion to test_minirunner_fixtures.py. Pins mark.parametrize and the
skip/xfail family, the tmp_path/monkeypatch/capsys built-ins, and the P3-2
scenario itself: a candidate that uses a repo's conftest fixture catching a
real seeded regression through the real differential oracle.
"""
from __future__ import annotations

import contextlib
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
from jittest.execute import Outcome, differential_check, run_test


def _write(body: str, stem: str, conftest: str | None = None) -> tuple[Path, Path]:
    directory = Path(tempfile.mkdtemp(prefix="jittest-fx2-"))
    path = directory / f"{stem}.py"
    path.write_text(body, encoding="utf-8")
    if conftest is not None:
        (directory / "conftest.py").write_text(conftest, encoding="utf-8")
    return directory, path


@contextlib.contextmanager
def _chdir(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _run(path: Path) -> int:
    with _chdir(path.parent):
        return run_file(path)


class ParametrizationAndMarks(unittest.TestCase):
    """mark.parametrize and the skip/xfail family."""

    def test_parametrize_expands_stacked_layers(self) -> None:
        directory, path = _write(
            "import os\nimport pytest\n\n"
            "COUNT = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                     'cases.txt')\n\n\n"
            "@pytest.mark.parametrize('a', [1, 2])\n"
            "@pytest.mark.parametrize('b', [10, 20], ids=['ten', 'twenty'])\n"
            "def test_sum(a, b):\n"
            "    with open(COUNT, 'a') as fh:\n        fh.write(f'{a + b}\\n')\n"
            "    assert a + b > 10\n",
            "t_param",
        )
        self.assertEqual(_run(path), EXIT_OK)
        seen = (directory / "cases.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(seen), ["11", "12", "21", "22"])

    def test_parametrize_accepts_pytest_param_ids(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n"
            "@pytest.mark.parametrize('value', [pytest.param(3, id='three')])\n"
            "def test_value(value):\n    assert value == 3\n",
            "t_pparam",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_mark_skip_decorated_tests_do_not_execute(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.mark.skip(reason='not here')\n"
            "def test_skipped():\n    assert True\n",
            "t_mskip",
        )
        self.assertEqual(_run(path), EXIT_NO_TESTS)

    def test_mark_skipif_honours_the_condition(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.mark.skipif(True, reason='yes')\n"
            "def test_skipped():\n    assert True\n\n\n"
            "@pytest.mark.skipif(False, reason='no')\n"
            "def test_runs():\n    assert True\n",
            "t_skipif",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_an_xfailed_failure_is_not_an_execution_and_not_a_failure(self) -> None:
        # An xfailed test proved nothing, exactly like a skipped one: it must
        # not satisfy the oracle's "a test really ran" requirement, and it
        # must not fail the file either.
        _dir, path = _write(
            "import pytest\n\n\n@pytest.mark.xfail(reason='known')\n"
            "def test_known_bug():\n    assert False\n",
            "t_xfail",
        )
        self.assertEqual(_run(path), EXIT_NO_TESTS)

    def test_an_xpass_counts_as_an_execution(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.mark.xfail(reason='maybe')\n"
            "def test_now_passing():\n    assert True\n",
            "t_xpass",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_a_strict_xpass_is_a_failure(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.mark.xfail(reason='s', strict=True)\n"
            "def test_now_passing():\n    assert True\n",
            "t_xstrict",
        )
        self.assertEqual(_run(path), EXIT_FAILED)

    def test_pytest_skip_in_the_body_skips(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\ndef test_body_skip():\n"
            "    pytest.skip('not applicable')\n",
            "t_bodyskip",
        )
        self.assertEqual(_run(path), EXIT_NO_TESTS)


class BuiltinFixtures(unittest.TestCase):
    """tmp_path, tmp_path_factory, monkeypatch, capsys."""

    def test_tmp_path_is_a_real_writable_directory(self) -> None:
        _dir, path = _write(
            "def test_tmp(tmp_path):\n"
            "    target = tmp_path / 'out.txt'\n"
            "    target.write_text('x')\n"
            "    assert target.read_text() == 'x'\n",
            "t_tmppath",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_tmp_path_factory_makes_directories(self) -> None:
        _dir, path = _write(
            "def test_factory(tmp_path_factory):\n"
            "    made = tmp_path_factory.mktemp('data')\n"
            "    assert made.is_dir()\n",
            "t_tmpfactory",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_monkeypatch_undoes_between_tests(self) -> None:
        _dir, path = _write(
            "import os\n\n\n"
            "def test_a_sets_the_var(monkeypatch):\n"
            "    monkeypatch.setenv('JT_FIXTURE_UNDO', 'set')\n"
            "    assert os.environ['JT_FIXTURE_UNDO'] == 'set'\n\n\n"
            "def test_b_the_var_is_gone():\n"
            "    assert 'JT_FIXTURE_UNDO' not in os.environ\n",
            "t_mpundo",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_capsys_captures_printed_output(self) -> None:
        _dir, path = _write(
            "def test_caps(capsys):\n"
            "    print('hello-jittest')\n"
            "    captured = capsys.readouterr()\n"
            "    assert 'hello-jittest' in captured.out\n",
            "t_capsys",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_import_pytest_works_via_the_shim(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n"
            "def test_raises_and_approx():\n"
            "    with pytest.raises(ValueError, match='bad'):\n"
            "        raise ValueError('bad input')\n"
            "    assert 0.1 + 0.2 == pytest.approx(0.3)\n",
            "t_shimapi",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_collection_error_is_still_two(self) -> None:
        _dir, path = _write("import nonexistent_module_xyz\n", "t_broken")
        self.assertEqual(_run(path), EXIT_COLLECTION_ERROR)


class _ForceMiniRunner(unittest.TestCase):
    """Pin the runner so these tests do not depend on pytest being absent."""

    def setUp(self) -> None:
        self._previous = os.environ.get("JITTEST_FORCE_MINIRUNNER")
        os.environ["JITTEST_FORCE_MINIRUNNER"] = "1"

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("JITTEST_FORCE_MINIRUNNER", None)
        else:
            os.environ["JITTEST_FORCE_MINIRUNNER"] = self._previous


def _git(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, errors="replace", check=True,
    )
    return done.stdout.strip()


_CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef two():\n    return 2\n"

_FIXTURED_CANDIDATE = (
    "from mod import calc\n\n\n"
    "def test_calc_doubles(two):\n    assert calc(two) == 4\n"
)


def _repo_with_conftest() -> tuple[Path, str, str]:
    root = Path(tempfile.mkdtemp(prefix="jittest-p32-"))
    _git("init", "--quiet", cwd=root)
    _git("config", "user.email", "tests@jittest.invalid", cwd=root)
    _git("config", "user.name", "jittest tests", cwd=root)
    (root / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
    (root / "mod.py").write_text("def calc(x):\n    return x * 2\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "--quiet", "-m", "base", cwd=root)
    base = _git("rev-parse", "HEAD", cwd=root)
    (root / "mod.py").write_text("def calc(x):\n    return x * 3\n", encoding="utf-8")
    _git("add", "-A", cwd=root)
    _git("commit", "--quiet", "-m", "head", cwd=root)
    head = _git("rev-parse", "HEAD", cwd=root)
    return root, base, head


class EndToEndThroughTheOracle(_ForceMiniRunner):
    """A conftest-fixture candidate used to be silently discarded. Not now."""

    def test_a_candidate_using_a_conftest_fixture_runs_in_a_workdir(self) -> None:
        workdir = Path(tempfile.mkdtemp(prefix="jittest-wd-"))
        (workdir / "conftest.py").write_text(_CONFTEST, encoding="utf-8")
        result = run_test(
            workdir, "def test_the_fixture(two):\n    assert two == 2\n")
        self.assertIs(result.outcome, Outcome.PASS)

    def test_the_p32_scenario_a_conftest_fixture_candidate_catches(self) -> None:
        # The adoption blocker itself: a repo whose tests rely on conftest
        # fixtures. The candidate asks for the conftest's fixture; base is
        # correct (calc doubles), head is broken (calc triples).
        root, base, head = _repo_with_conftest()
        verdict = differential_check(root, base, head, _FIXTURED_CANDIDATE,
                                     reruns=2)
        self.assertTrue(verdict.is_catching, verdict.reason)
        self.assertIs(verdict.head_outcome, Outcome.FAIL)
        self.assertIs(verdict.base_outcome, Outcome.PASS)

    def test_testcase_classes_get_setup_and_teardown(self) -> None:
        directory, path = _write(
            "import os\nimport unittest\n\n"
            "MARK = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                    'tc.txt')\n\n\n"
            "class TestThing(unittest.TestCase):\n"
            "    def setUp(self):\n"
            "        with open(MARK, 'a') as fh:\n            fh.write('setup\\n')\n"
            "    def tearDown(self):\n"
            "        with open(MARK, 'a') as fh:\n"
            "            fh.write('teardown\\n')\n"
            "    def test_one(self):\n"
            "        with open(MARK, 'a') as fh:\n            fh.write('test\\n')\n"
            "        self.assertTrue(True)\n",
            "t_tcase",
        )
        self.assertEqual(_run(path), EXIT_OK)
        marks = (directory / "tc.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(marks, ["setup", "test", "teardown"])

    def test_plain_classes_use_setup_method_and_method_fixtures(self) -> None:
        _dir, path = _write(
            "class TestGroup:\n"
            "    def setup_method(self, method):\n        self.ready = True\n"
            "    def test_it(self, tmp_path):\n"
            "        assert self.ready\n        assert tmp_path.is_dir()\n",
            "t_pclass",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_classes_with_constructors_are_not_collected(self) -> None:
        _dir, path = _write(
            "class TestWithInit:\n"
            "    def __init__(self):\n        self.x = 1\n"
            "    def test_it(self):\n        assert self.x == 1\n",
            "t_withinit",
        )
        self.assertEqual(_run(path), EXIT_NO_TESTS)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(unittest.main())
