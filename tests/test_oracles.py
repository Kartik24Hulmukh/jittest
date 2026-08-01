"""Tests for the oracle-strength scanner.

The scanner's entire value is that its verdicts are trustworthy, so these tests
are deliberately literal: one case per taxonomy category, plus the properties
that must hold no matter what input arrives - determinism, no source-code leak,
and the refusal to report a rate for zero tests.
"""
from __future__ import annotations

import contextlib
import io
import json
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jittest.cli import main
from jittest.oracles import (
    CATEGORIES,
    OracleScanError,
    scan_paths,
    scan_source,
    to_markdown,
    to_terminal,
)


def verdict(body: str) -> str:
    source = textwrap.dedent(body)
    found = scan_source(source, "tests/test_sample.py")
    assert len(found.tests) == 1, f"expected one test function, got {len(found.tests)}"
    return found.tests[0].verdict


class WeakOracles(unittest.TestCase):
    def test_w1_no_assertion_at_all(self):
        self.assertEqual(verdict("""
            def test_it():
                result = compute(2)
                print(result)
        """), "W1")

    def test_w1_vacuous_constant_assertion(self):
        self.assertEqual(verdict("""
            def test_it():
                compute(2)
                assert True
        """), "W1")

    def test_w2_bare_truthiness_of_a_name(self):
        self.assertEqual(verdict("""
            def test_it():
                result = compute(2)
                assert result
        """), "W2")

    def test_w2_is_not_none(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) is not None
        """), "W2")

    def test_w2_unittest_assert_is_not_none(self):
        self.assertEqual(verdict("""
            class TestThing:
                def test_it(self):
                    self.assertIsNotNone(compute(2))
        """), "W2")

    def test_w3_assert_true(self):
        self.assertEqual(verdict("""
            class TestThing:
                def test_it(self):
                    self.assertTrue(compute(2))
        """), "W3")

    def test_w3_compare_against_a_boolean_literal(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) is True
        """), "W3")

    def test_w4_mock_verification_only(self):
        self.assertEqual(verdict("""
            def test_it(mocker):
                sink = mocker.Mock()
                emit(sink)
                sink.assert_called_once_with(2)
        """), "W4")

    def test_w5_snapshot_only(self):
        self.assertEqual(verdict("""
            def test_it(snapshot):
                assert render() == snapshot
        """), "W5")


class StrongOracles(unittest.TestCase):
    def test_s1_value_equality(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) == 4
        """), "S1")

    def test_s1_unittest_assert_equal(self):
        self.assertEqual(verdict("""
            class TestThing:
                def test_it(self):
                    self.assertEqual(compute(2), 4)
        """), "S1")

    def test_s1_ordering(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) > 3
        """), "S1")

    def test_s1_membership(self):
        self.assertEqual(verdict("""
            def test_it():
                assert "needle" in render()
        """), "S1")

    def test_s2_pytest_raises(self):
        self.assertEqual(verdict("""
            def test_it():
                with pytest.raises(ValueError):
                    compute(-1)
        """), "S2")

    def test_s2_isinstance(self):
        self.assertEqual(verdict("""
            def test_it():
                assert isinstance(compute(2), int)
        """), "S2")

    def test_s3_two_strong_signals(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) == 4
                assert compute(3) == 9
        """), "S3")

    def test_s3_mixed_strong_signals(self):
        self.assertEqual(verdict("""
            def test_it():
                assert compute(2) == 4
                with pytest.raises(ValueError):
                    compute(-1)
        """), "S3")


class DiscriminationRules(unittest.TestCase):
    def test_a_bare_raises_is_not_credited_as_pytest(self):
        # A project-local helper called `raises` must not inflate the rate.
        self.assertEqual(verdict("""
            def test_it():
                with raises(ValueError):
                    compute(-1)
        """), "W1")

    def test_strong_signal_beats_weak_signal_in_the_same_test(self):
        self.assertEqual(verdict("""
            def test_it():
                result = compute(2)
                assert result
                assert result == 4
        """), "S1")

    def test_async_test_functions_are_scanned(self):
        self.assertEqual(verdict("""
            async def test_it():
                assert await compute(2) == 4
        """), "S1")

    def test_non_test_functions_are_ignored(self):
        found = scan_source(textwrap.dedent("""
            def helper():
                assert False

            def test_it():
                assert compute(2) == 4
        """), "tests/test_sample.py")
        self.assertEqual([t.name for t in found.tests], ["test_it"])

    def test_unparseable_file_is_reported_not_crashed(self):
        found = scan_source("def test_it(:\n    pass\n", "tests/test_bad.py")
        self.assertEqual(found.tests, [])
        self.assertIn("SyntaxError", found.parse_error)

    def test_parse_error_never_contains_the_source_line(self):
        secret = "SUPER_SECRET_LITERAL_9127"
        found = scan_source(f"def test_it(:\n    x = '{secret}'\n", "tests/t.py")
        self.assertNotIn(secret, json.dumps(found.as_dict()))


class ReportProperties(unittest.TestCase):
    def _report(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tests").mkdir()
            (root / "tests" / "test_weak.py").write_text(
                "def test_a():\n    assert compute(2)\n", encoding="utf-8")
            (root / "tests" / "test_strong.py").write_text(
                "def test_b():\n    assert compute(2) == 4\n", encoding="utf-8")
            return scan_paths(root, ["tests"])

    def test_directory_scan_finds_both_files(self):
        report = self._report()
        self.assertEqual(report.total, 2)
        self.assertEqual(report.strong, 1)
        self.assertEqual(report.weak, 1)
        self.assertAlmostEqual(report.strong_rate, 0.5)

    def test_files_are_ordered_deterministically(self):
        paths = [f.path for f in self._report().files]
        self.assertEqual(paths, sorted(paths))

    def test_repeated_scans_agree_exactly(self):
        source = textwrap.dedent("""
            def test_one():
                assert compute(2) == 4

            def test_two():
                compute(3)
        """)
        first = scan_source(source, "tests/test_x.py").as_dict()
        for _ in range(32):
            self.assertEqual(scan_source(source, "tests/test_x.py").as_dict(), first)

    def test_empty_scan_reports_no_rate_rather_than_zero(self):
        report = scan_paths(Path("."), [])
        self.assertEqual(report.total, 0)
        self.assertIsNone(report.strong_rate)
        self.assertIn("no rate to report", to_terminal(report) + to_markdown(report))

    def test_every_category_key_is_present_in_the_breakdown(self):
        counts = self._report().by_category()
        self.assertEqual(sorted(counts), sorted(CATEGORIES))

    def test_missing_path_raises_rather_than_returning_empty(self):
        with self.assertRaises(OracleScanError):
            scan_paths(Path("."), ["definitely/not/here_9127.py"])

    def test_renderers_never_emit_test_source(self):
        secret = "SUPER_SECRET_LITERAL_9127"
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "test_leak.py"
            target.write_text(
                f"def test_a():\n    value = '{secret}'\n    assert value\n",
                encoding="utf-8")
            report = scan_paths(root, [str(target)])
        rendered = to_terminal(report) + to_markdown(report) + json.dumps(
            report.as_dict())
        self.assertNotIn(secret, rendered)


class CommandLine(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv)
        return code, buf.getvalue()

    def test_json_output_is_valid_json(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "test_ok.py"
            target.write_text("def test_a():\n    assert compute(2) == 4\n",
                              encoding="utf-8")
            code, out = self._run(["oracles", str(target), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["totals"]["strong"], 1)

    def test_fail_under_gate_exits_one_when_the_rate_is_too_low(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "test_weak.py"
            target.write_text("def test_a():\n    compute(2)\n", encoding="utf-8")
            code, _ = self._run(["oracles", str(target), "--fail-under", "0.5"])
        self.assertEqual(code, 1)

    def test_fail_under_gate_passes_when_the_rate_is_high_enough(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "test_ok.py"
            target.write_text("def test_a():\n    assert compute(2) == 4\n",
                              encoding="utf-8")
            code, _ = self._run(["oracles", str(target), "--fail-under", "1.0"])
        self.assertEqual(code, 0)

    def test_fail_under_does_not_fire_when_nothing_was_scanned(self):
        # No tests means no evidence, and no evidence must never be reported as
        # a failing measurement. This is the same rule the eval harness applies
        # to catch rate.
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "test_empty.py"
            target.write_text("CONSTANT = 1\n", encoding="utf-8")
            code, _ = self._run(["oracles", str(target), "--fail-under", "1.0"])
        self.assertEqual(code, 0)

    def test_unknown_path_exits_two(self):
        code, _ = self._run(["oracles", "definitely/not/here_9127.py"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
