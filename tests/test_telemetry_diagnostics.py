"""Track C3: safety_rejected and parse_failed must be diagnosable after the run.

The only completed eval run produced seven safety_rejected and three
parse_failed candidates, each recorded as a bare label. All ten are
permanently undiagnosable. These tests pin the two fields that fix that, and
equally importantly pin the boundary on what the parse_failed field is allowed
to contain.
"""
from __future__ import annotations

import ast
import json
import unittest

from jittest._pipeline_helpers import _telemetry, parse_failure_digest
from jittest.results import CandidateTelemetry, Report


class _Target:
    symbol = "innermost"
    file_path = "pkg/core.py"


class _Risk:
    score = 0.42


def _report():
    return Report(repo="r", base="b", head="h", model="m")


def _syntax_error(src: str) -> SyntaxError:
    try:
        ast.parse(src)
    except SyntaxError as exc:
        return exc
    raise AssertionError("source unexpectedly parsed")


class TelemetryFieldsTest(unittest.TestCase):
    def test_telemetry_defaults_are_empty_not_missing(self):
        """Both fields always serialise, so a consumer can rely on the key."""
        d = CandidateTelemetry().as_dict()
        self.assertIn("check_reason", d)
        self.assertIn("parse_error", d)
        self.assertEqual(d["check_reason"], "")
        self.assertEqual(d["parse_error"], "")

    def test_safety_rejected_carries_the_gate_reason(self):
        rep = _report()
        _telemetry(rep, _Target(), _Risk(), 1, "safety_rejected",
                   check_reason="imports subprocess")
        tel = rep.telemetry[0]
        self.assertEqual(tel.disposition, "safety_rejected")
        self.assertEqual(tel.check_reason, "imports subprocess")
        self.assertEqual(json.loads(tel.as_jsonl())["check_reason"],
                         "imports subprocess")

    def test_parse_failed_carries_a_digest(self):
        rep = _report()
        _telemetry(rep, _Target(), _Risk(), 2, "parse_failed",
                   parse_error="invalid syntax at line 3, col 1; len=40 "
                               "lines=3 fenced=no sha256=deadbeefcafe")
        tel = rep.telemetry[0]
        self.assertEqual(tel.disposition, "parse_failed")
        self.assertIn("sha256=", tel.parse_error)

    def test_fields_are_length_capped(self):
        """An unbounded field in a per-candidate record is a log bomb."""
        rep = _report()
        _telemetry(rep, _Target(), _Risk(), 1, "safety_rejected",
                   check_reason="x" * 5000, parse_error="y" * 5000)
        tel = rep.telemetry[0]
        self.assertLessEqual(len(tel.check_reason), 300)
        self.assertLessEqual(len(tel.parse_error), 300)


class ParseFailureDigestTest(unittest.TestCase):
    def test_digest_reports_shape_not_text(self):
        src = "def test_x(:\n    assert SECRET_TOKEN == 'hunter2'\n"
        digest = parse_failure_digest(src, _syntax_error(src))
        # The questions an operator has, answered.
        self.assertIn("len=", digest)
        self.assertIn("lines=", digest)
        self.assertIn("fenced=", digest)
        self.assertIn("sha256=", digest)
        # The candidate body, absent.
        self.assertNotIn("SECRET_TOKEN", digest)
        self.assertNotIn("hunter2", digest)
        self.assertNotIn("assert", digest)
        self.assertNotIn("def test_x", digest)

    def test_digest_excludes_the_offending_source_line(self):
        """SyntaxError.text holds the raw line. It must never be included."""
        src = "value = PRIVATE_CONSTANT_NAME ===\n"
        exc = _syntax_error(src)
        digest = parse_failure_digest(src, exc)
        self.assertNotIn("PRIVATE_CONSTANT_NAME", digest)
        if getattr(exc, "text", None):
            self.assertNotIn(exc.text.strip(), digest)

    def test_digest_is_stable_for_identical_text(self):
        """Repeated identical failures must be recognisable as repeats."""
        src = "def broken(:\n    pass\n"
        a = parse_failure_digest(src, _syntax_error(src))
        b = parse_failure_digest(src, _syntax_error(src))
        self.assertEqual(a, b)

    def test_digest_distinguishes_different_text(self):
        one = "def broken(:\n    pass\n"
        two = "def other(:\n    pass\n"
        self.assertNotEqual(parse_failure_digest(one, _syntax_error(one)),
                            parse_failure_digest(two, _syntax_error(two)))

    def test_digest_detects_a_fence(self):
        fenced = "```python\ndef broken(:\n    pass\n```\n"
        self.assertIn("fenced=yes",
                      parse_failure_digest(fenced, _syntax_error(fenced)))
        plain = "def broken(:\n    pass\n"
        self.assertIn("fenced=no",
                      parse_failure_digest(plain, _syntax_error(plain)))


if __name__ == "__main__":
    unittest.main()
