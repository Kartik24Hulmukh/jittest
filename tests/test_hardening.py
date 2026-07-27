"""Regression tests for the hardening pass of 27 July 2026.

Each test here corresponds to a construct that an adversarial sweep found was
accepted, mis-typed or silently dropped before. They exist so the next person
to simplify one of these checks has to argue with a failing test first.
"""
import pathlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from jittest.assess import parse_assessment
from jittest.config import Config, load_config, normalise_values
from jittest.diff import is_safe_repo_path, parse_unified_diff
from jittest.safety import check_candidate


class TestSafetyGateBypasses(unittest.TestCase):
    """16 payloads that the first version of the gate let through."""

    REJECTED = {
        "from-os-import-system":
            "from os import system\ndef test_x():\n    system('id')\n    assert 1 == 1\n",
        "from-os-import-popen":
            "from os import popen\ndef test_x():\n    popen('id')\n    assert 1 == 1\n",
        "from-os-import-remove":
            "from os import remove\ndef test_x():\n    remove('x')\n    assert 1 == 1\n",
        "alias-eval":
            "def test_x():\n    f = eval\n    f('1')\n    assert 1 == 1\n",
        "alias-exec-module-level":
            "g = exec\ndef test_x():\n    g('x=1')\n    assert 1 == 1\n",
        "computed-getattr":
            "import os\ndef test_x():\n    getattr(os, 'sys' + 'tem')('id')\n    assert 1 == 1\n",
        "importlib":
            "import importlib\ndef test_x():\n    assert importlib.import_module('socket')\n",
        "builtins-module":
            "import builtins\ndef test_x():\n    builtins.eval('1')\n    assert 1 == 1\n",
        "runpy":
            "import runpy\ndef test_x():\n    runpy.run_module('socket')\n    assert 1 == 1\n",
        "mro-subclasses-gadget":
            "def test_x():\n    assert ''.__class__.__mro__[1].__subclasses__()\n",
        "func-globals-gadget":
            "def test_x():\n    assert test_x.__globals__ is not None\n",
        "globals-builtin":
            "def test_x():\n    globals()['__name__']\n    assert 1 == 1\n",
        "destructive-unlink":
            "import pathlib\ndef test_x():\n"
            "    pathlib.Path('src/jittest/risk.py').unlink()\n    assert 1 == 1\n",
        "oracle-tamper-write-text":
            "import pathlib\ndef test_x():\n"
            "    pathlib.Path('src/jittest/risk.py').write_text('')\n    assert 1 == 1\n",
        "oracle-tamper-open-w":
            "def test_x():\n    open('src/jittest/risk.py', 'w')\n    assert 1 == 1\n",
        "assert-constant-int": "def test_x():\n    assert 1\n",
        "assert-constant-str": "def test_x():\n    assert 'yes'\n",
    }

    ACCEPTED = {
        "plain": "def test_x():\n    assert 1 + 1 == 2\n",
        "math": "import math\ndef test_x():\n    assert math.floor(1.5) == 1\n",
        "json": "import json\ndef test_x():\n    assert json.loads('[1]') == [1]\n",
        "tempfile":
            "import tempfile\ndef test_x():\n"
            "    with tempfile.NamedTemporaryFile() as fh:\n        assert fh.name\n",
        "constant-getattr":
            "def test_x():\n    class A:\n        b = 2\n    assert getattr(A, 'b') == 2\n",
        "str-replace-is-not-os-replace":
            "def test_x():\n    assert 'ab'.replace('a', 'c') == 'cb'\n",
        "list-remove-is-not-os-remove":
            "def test_x():\n    xs = [1, 2]\n    xs.remove(1)\n    assert xs == [2]\n",
        "file-write-on-handle":
            "import io\ndef test_x():\n    buf = io.StringIO()\n"
            "    buf.write('x')\n    assert buf.getvalue() == 'x'\n",
        "open-for-reading":
            "def test_x():\n    try:\n        open('setup.cfg')\n"
            "    except OSError:\n        pass\n    assert 1 == 1\n",
        "dunder-class-is-allowed":
            "def test_x():\n    assert 'a'.__class__ is str\n",
    }

    def test_dangerous_payloads_are_rejected(self):
        for label, code in self.REJECTED.items():
            with self.subTest(payload=label):
                check = check_candidate(code)
                self.assertFalse(check.ok, f"{label} was accepted")
                self.assertTrue(check.reason, f"{label} rejected without a reason")

    def test_ordinary_test_code_is_still_accepted(self):
        for label, code in self.ACCEPTED.items():
            with self.subTest(payload=label):
                check = check_candidate(code)
                self.assertTrue(check.ok, f"{label} was rejected: {check.reason}")

    def test_assert_true_keeps_its_original_message(self):
        check = check_candidate("def test_x():\n    assert True\n")
        self.assertFalse(check.ok)
        self.assertIn("assert True", check.reason)

    def test_null_bytes_do_not_raise(self):
        check = check_candidate("def test_x():\n    assert 1 == 1\x00\n")
        self.assertFalse(check.ok)

    def test_gate_never_raises_on_arbitrary_bytes(self):
        import random

        random.seed(3)
        alphabet = "\n\t abc(){}[]:=,.'\"#\\def import\x00"
        for _ in range(500):
            blob = "".join(random.choice(alphabet)
                           for _ in range(random.randint(0, 80)))
            check_candidate(blob)          # must not raise


class TestConfigNormalisation(unittest.TestCase):

    def test_non_finite_numbers_fall_back_to_defaults(self):
        for raw in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(raw=raw):
                clean, notes = normalise_values({"budget_usd": raw})
                self.assertTrue(math.isfinite(clean["budget_usd"]))
                self.assertTrue(notes)

    def test_out_of_range_values_are_clamped(self):
        clean, notes = normalise_values(
            {"risk_threshold": 5.0, "max_targets": -3, "timeout_s": 0, "reruns": -2})
        self.assertEqual(clean["risk_threshold"], 1.0)
        self.assertEqual(clean["max_targets"], 1)
        self.assertEqual(clean["timeout_s"], 1)
        self.assertEqual(clean["reruns"], 0)
        self.assertEqual(len(notes), 4)

    def test_wrong_types_fall_back_to_defaults(self):
        clean, notes = normalise_values(
            {"budget_usd": "lots", "max_targets": "five", "model": ["a"],
             "ignore": "notalist"})
        self.assertEqual(clean["budget_usd"], 1.00)
        self.assertEqual(clean["max_targets"], 5)
        self.assertEqual(clean["model"], Config().model)
        self.assertNotIn("ignore", clean)
        self.assertEqual(len(notes), 4)

    def test_boolean_is_not_accepted_as_a_number(self):
        clean, _ = normalise_values({"budget_usd": True})
        self.assertEqual(clean["budget_usd"], 1.00)
        self.assertNotIsInstance(clean["budget_usd"], bool)

    def test_unknown_options_are_dropped_not_crashed_on(self):
        clean, notes = normalise_values({"nonsense": 1})
        self.assertEqual(clean, {})
        self.assertIn("nonsense", notes[0])

    def test_hostile_env_still_yields_strict_json_config(self):
        cases = {
            "JITTEST_BUDGET_USD": ["nan", "inf", "-1", "1e400", "abc"],
            "JITTEST_RISK_THRESHOLD": ["2.5", "-0.5", "nan"],
            "JITTEST_MAX_TARGETS": ["-5", "0"],
            "JITTEST_TIMEOUT": ["0", "-1"],
            "JITTEST_RERUNS": ["-2"],
        }
        with tempfile.TemporaryDirectory() as repo:
            for var, values in cases.items():
                for raw in values:
                    with self.subTest(var=var, value=raw):
                        os.environ[var] = raw
                        try:
                            cfg = load_config(repo)
                            payload = cfg.as_dict()
                            json.dumps(payload, allow_nan=False)
                            self.assertGreaterEqual(payload["budget_usd"], 0.0)
                            self.assertGreaterEqual(payload["max_targets"], 1)
                            self.assertGreaterEqual(payload["timeout_s"], 1)
                            self.assertGreaterEqual(payload["reruns"], 0)
                            self.assertTrue(0.0 <= payload["risk_threshold"] <= 1.0)
                        finally:
                            del os.environ[var]

    def test_notes_are_attached_but_not_serialised(self):
        with tempfile.TemporaryDirectory() as repo:
            Path(repo, ".jittest.toml").write_text(
                "risk_threshold = 9.0\n", encoding="utf-8")
            cfg = load_config(repo)
        self.assertTrue(getattr(cfg, "notes", ()))
        self.assertNotIn("notes", cfg.as_dict())

    def test_broken_toml_is_survivable(self):
        with tempfile.TemporaryDirectory() as repo:
            Path(repo, ".jittest.toml").write_text("not toml [[[\n", encoding="utf-8")
            cfg = load_config(repo)
        self.assertEqual(cfg.model, Config().model)


class TestDiffPathSafety(unittest.TestCase):

    UNSAFE = ["../../etc/passwd", "/etc/shadow", "a/../../b.py", "C:/Windows/x.py",
              "..\\..\\x.py", "", "x\x00.py"]
    SAFE = ["calc.py", "src/jittest/risk.py", "a/b/c.py", "my file.py",
            "pkg/..hidden/x.py"]

    def test_unsafe_paths_are_rejected(self):
        for path in self.UNSAFE:
            with self.subTest(path=path):
                self.assertFalse(is_safe_repo_path(path))

    def test_ordinary_paths_are_accepted(self):
        for path in self.SAFE:
            with self.subTest(path=path):
                self.assertTrue(is_safe_repo_path(path))

    def test_quoted_paths_with_spaces_are_parsed(self):
        text = ('diff --git "a/my file.py" "b/my file.py"\n'
                '--- "a/my file.py"\n+++ "b/my file.py"\n'
                "@@ -1 +1 @@\n-a = 1\n+a = 2\n")
        files = parse_unified_diff(text)
        self.assertEqual([f.path for f in files], ["my file.py"])

    def test_plain_paths_still_parse_unchanged(self):
        text = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
                "@@ -1,2 +1,2 @@\n-a = 1\n+a = 2\n b = 3\n")
        files = parse_unified_diff(text)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].path, "calc.py")
        self.assertEqual(files[0].old_path, "calc.py")
        self.assertEqual(files[0].added_lines, [1])
        self.assertEqual(files[0].removed_lines, [1])

    def test_parser_never_raises_on_mutated_diffs(self):
        import random

        base = ("diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
                "@@ -1,2 +1,2 @@\n-a = 1\n+a = 2\n")
        random.seed(5)
        for _ in range(400):
            chars = list(base)
            for _ in range(random.randint(1, 10)):
                if not chars:
                    break
                i = random.randrange(len(chars))
                if random.random() < 0.5:
                    del chars[i]
                else:
                    chars.insert(i, random.choice("@+- /\n0123456789\"\x00"))
            parse_unified_diff("".join(chars))     # must not raise


class TestAssessorCoercion(unittest.TestCase):

    def test_confidence_is_always_finite_and_json_safe(self):
        payloads = [
            {"verdict": "real_regression", "confidence": float("nan")},
            {"verdict": "real_regression", "confidence": float("inf")},
            {"verdict": "real_regression", "confidence": float("-inf")},
            {"verdict": "real_regression", "confidence": "nan"},
            {"verdict": "real_regression", "confidence": [1]},
            None,
        ]
        for payload in payloads:
            with self.subTest(payload=payload):
                a = parse_assessment(payload)
                self.assertTrue(math.isfinite(a.confidence))
                json.dumps(a.as_dict(), allow_nan=False)

    def test_percentage_confidence_is_rescaled(self):
        a = parse_assessment({"verdict": "real_regression", "confidence": 85})
        self.assertEqual(a.confidence, 0.85)
        self.assertTrue(a.should_report)

    def test_unknown_verdict_cannot_report(self):
        a = parse_assessment({"verdict": "DEFINITELY_A_BUG", "confidence": 0.99})
        self.assertEqual(a.verdict, "unclear")
        self.assertFalse(a.should_report)


if __name__ == "__main__":
    unittest.main()


class TestVersionConsistency(unittest.TestCase):
    """The version is declared twice: pyproject.toml [project].version and
    jittest.__version__. Nothing kept them in sync, and they had already
    drifted (pyproject 0.2.2 vs __init__ 0.2.1) during the hardening pass.
    A released wheel whose runtime __version__ disagrees with its metadata
    makes every bug report ambiguous."""

    def _pyproject_version(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / "pyproject.toml").read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("version = "):
                return stripped.split("=", 1)[1].strip().strip('"')
        return None

    def test_runtime_version_matches_pyproject(self):
        import jittest

        declared = self._pyproject_version()
        self.assertIsNotNone(declared, "no version found in pyproject.toml")
        self.assertEqual(jittest.__version__, declared)
