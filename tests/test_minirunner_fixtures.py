"""Roadmap P3-2: pytest fixture support in the mini-runner.

Before this existed, a candidate written for a pytest-native repository - one
that does ``import pytest`` and uses fixtures from the repo's conftest.py -
either died at collection or was silently skipped, and jittest caught nothing
in that repository while saying nothing. These tests pin the new behaviour:
conftest fixtures resolve, fixtures may use fixtures, scopes/teardown/autouse
work, and unknown fixtures fail loudly. See test_minirunner_fixtures_e2e.py
for marks, built-ins and the end-to-end oracle scenario.
"""
from __future__ import annotations

import contextlib
import os
import tempfile
import unittest
from pathlib import Path

from jittest import _pytestshim as shim
from jittest._minirunner import (
    EXIT_COLLECTION_ERROR,
    EXIT_FAILED,
    EXIT_NO_TESTS,
    EXIT_OK,
    run_file,
)


def _write(body: str, stem: str, conftest: str | None = None) -> tuple[Path, Path]:
    directory = Path(tempfile.mkdtemp(prefix="jittest-fix-"))
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
    """run_file with cwd at the candidate's directory, matching how
    execute.run_test invokes the runner (cwd=workdir)."""
    with _chdir(path.parent):
        return run_file(path)


class ShimPrimitives(unittest.TestCase):
    """The pytest-shaped pieces, unit-tested directly."""

    def test_raises_catches_the_expected_exception(self) -> None:
        with shim.raises(ValueError):
            raise ValueError("boom")

    def test_raises_fails_when_nothing_is_raised(self) -> None:
        with self.assertRaises(shim.Failed):
            with shim.raises(ValueError):
                pass

    def test_raises_with_match(self) -> None:
        with shim.raises(ValueError, match="boom"):
            raise ValueError("boom goes the dynamite")
        with self.assertRaises(shim.Failed):
            with shim.raises(ValueError, match="quiet"):
                raise ValueError("boom")

    def test_raises_passes_on_the_wrong_exception(self) -> None:
        with self.assertRaises(TypeError):
            with shim.raises(ValueError):
                raise TypeError("wrong kind")

    def test_approx_scalar_list_and_dict(self) -> None:
        self.assertTrue(0.1 + 0.2 == shim.approx(0.3))
        self.assertTrue([1.0, 2.0000001] == shim.approx([1.0, 2.0]))
        self.assertTrue({"a": 1.0} == shim.approx({"a": 1.0000001}))
        self.assertFalse(0.5 == shim.approx(0.3))

    def test_monkeypatch_setattr_and_undo(self) -> None:
        class Target:
            value = 1

        mp = shim.MonkeyPatch()
        mp.setattr(Target, "value", 99)
        self.assertEqual(Target.value, 99)
        mp.undo()
        self.assertEqual(Target.value, 1)

    def test_monkeypatch_string_form_and_env(self) -> None:
        mp = shim.MonkeyPatch()
        mp.setattr("os.path.sep", "X")
        self.assertEqual(os.path.sep, "X")
        mp.setenv("JITTEST_TEST_ENV", "present")
        self.assertEqual(os.environ.get("JITTEST_TEST_ENV"), "present")
        mp.delenv("JITTEST_TEST_ENV")
        self.assertIsNone(os.environ.get("JITTEST_TEST_ENV"))
        mp.undo()
        self.assertNotEqual(os.path.sep, "X")

    def test_monkeypatch_setitem_and_delitem(self) -> None:
        mapping = {"a": 1}
        mp = shim.MonkeyPatch()
        mp.setitem(mapping, "b", 2)
        mp.delitem(mapping, "a")
        self.assertEqual(mapping, {"b": 2})
        mp.undo()
        self.assertEqual(mapping, {"a": 1})

    def test_importorskip_skips_on_missing_module(self) -> None:
        with self.assertRaises(shim.Skipped):
            shim.importorskip("nonexistent_module_xyz")
        self.assertIs(shim.importorskip("os"), os)

    def test_request_exposes_param_only_when_parametrized(self) -> None:
        plain = shim.FixtureRequest(fixturename="f")
        self.assertFalse(hasattr(plain, "param"))
        parametrized = shim.FixtureRequest(
            fixturename="f", has_param=True, param_value=7)
        self.assertEqual(parametrized.param, 7)

    def test_param_carries_values_and_id(self) -> None:
        entry = shim.param((1, 2), id="pair")
        self.assertEqual(entry.values, (1, 2))
        self.assertEqual(entry.id, "pair")


class FixtureResolution(unittest.TestCase):
    """conftest and module fixtures resolve through run_file."""

    def test_a_conftest_fixture_resolves(self) -> None:
        _dir, path = _write(
            "def test_the_answer(answer):\n    assert answer == 42\n",
            "t_conftest",
            conftest=(
                "import pytest\n\n\n@pytest.fixture\ndef answer():\n"
                "    return 42\n"
            ),
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_a_module_fixture_wins_over_conftest(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.fixture\ndef answer():\n"
            "    return 43\n\n\ndef test_the_answer(answer):\n"
            "    assert answer == 43\n",
            "t_override",
            conftest=(
                "import pytest\n\n\n@pytest.fixture\ndef answer():\n"
                "    return 42\n"
            ),
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_a_fixture_may_use_another_fixture(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.fixture\ndef base():\n    return 40\n\n\n"
            "@pytest.fixture\ndef answer(base):\n    return base + 2\n\n\n"
            "def test_the_answer(answer):\n    assert answer == 42\n",
            "t_chain",
        )
        self.assertEqual(_run(path), EXIT_OK)

    def test_a_yield_fixture_tears_down(self) -> None:
        directory, path = _write(
            "import os\nimport pytest\n\n"
            "MARK = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                    'marks.txt')\n\n\n"
            "@pytest.fixture\ndef resource():\n"
            "    with open(MARK, 'a') as fh:\n        fh.write('setup\\n')\n"
            "    yield 1\n"
            "    with open(MARK, 'a') as fh:\n        fh.write('teardown\\n')\n\n\n"
            "def test_resource(resource):\n    assert resource == 1\n",
            "t_yield",
        )
        self.assertEqual(_run(path), EXIT_OK)
        marks = (directory / "marks.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(marks, ["setup", "teardown"])

    def test_a_module_scoped_fixture_is_built_once(self) -> None:
        directory, path = _write(
            "import os\nimport pytest\n\n"
            "COUNT = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                     'count.txt')\n\n\n"
            "@pytest.fixture(scope='module')\ndef shared():\n"
            "    with open(COUNT, 'a') as fh:\n        fh.write('built\\n')\n"
            "    return object()\n\n\n"
            "def test_one(shared):\n    assert shared is not None\n\n\n"
            "def test_two(shared):\n    assert shared is not None\n",
            "t_scope",
        )
        self.assertEqual(_run(path), EXIT_OK)
        built = (directory / "count.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(built, ["built"])

    def test_an_autouse_fixture_runs_unrequested(self) -> None:
        directory, path = _write(
            "import os\nimport pytest\n\n"
            "MARK = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                    'auto.txt')\n\n\n"
            "@pytest.fixture(autouse=True)\ndef _marker():\n"
            "    with open(MARK, 'a') as fh:\n        fh.write('ran\\n')\n\n\n"
            "def test_plain():\n    assert True\n",
            "t_autouse",
        )
        self.assertEqual(_run(path), EXIT_OK)
        self.assertEqual(
            (directory / "auto.txt").read_text(encoding="utf-8").splitlines(),
            ["ran"],
        )

    def test_a_parametrized_fixture_expands_and_sees_request_param(self) -> None:
        directory, path = _write(
            "import os\nimport pytest\n\n"
            "COUNT = os.path.join(os.path.dirname(os.path.abspath(__file__)),\n"
            "                     'params.txt')\n\n\n"
            "@pytest.fixture(params=[1, 2], ids=['one', 'two'])\n"
            "def number(request):\n    return request.param\n\n\n"
            "def test_numbers(number):\n"
            "    with open(COUNT, 'a') as fh:\n        fh.write(f'{number}\\n')\n"
            "    assert number in (1, 2)\n",
            "t_fparams",
        )
        self.assertEqual(_run(path), EXIT_OK)
        seen = (directory / "params.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(sorted(seen), ["1", "2"])

    def test_an_unknown_fixture_fails_loudly_never_silently(self) -> None:
        _dir, path = _write(
            "def test_needs_a_fixture(nope_missing):\n    assert True\n",
            "t_unknown",
        )
        self.assertEqual(_run(path), EXIT_FAILED)

    def test_a_circular_fixture_dependency_fails_loudly(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.fixture\ndef alpha(beta):\n"
            "    return beta\n\n\n@pytest.fixture\ndef beta(alpha):\n"
            "    return alpha\n\n\ndef test_cycle(alpha):\n    assert True\n",
            "t_cycle",
        )
        self.assertEqual(_run(path), EXIT_FAILED)

    def test_an_async_fixture_fails_loudly(self) -> None:
        _dir, path = _write(
            "import pytest\n\n\n@pytest.fixture\nasync def thing():\n"
            "    yield 1\n\n\ndef test_thing(thing):\n    assert thing == 1\n",
            "t_asyncfx",
        )
        self.assertEqual(_run(path), EXIT_FAILED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
