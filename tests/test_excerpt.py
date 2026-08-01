"""The failure excerpt must diagnose without disclosing.

Two guarantees meet in `_excerpt`, and they pull against each other:

  Defect 68  the exception type and message must survive, or a failed
             evaluation cannot be diagnosed at all
  Defect 70  the candidate's source text must never reach telemetry,
             which is written to logs and public workflow artifacts

An earlier fix for 68 widened the window and broke 70. These tests pin
both halves so that cannot happen quietly again.
"""
from __future__ import annotations

import unittest

from jittest._pipeline_helpers import _excerpt, _strip_source_echo

# A real minirunner traceback, of the shape that run 30655481944 produced
# twenty byte-identical copies of.
TRACEBACK = """COLLECTION ERROR in test_jittest_candidate_3fcd95db.py
Traceback (most recent call last):
  File "/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/jittest/_minirunner.py", line 94, in _run_file
    module = _load(path)
             ^^^^^^^^^^^
  File "/tmp/jittest-eval/worktree/test_candidate.py", line 3, in <module>
    assert apply_discount(100.0, 150.0) == 0.0
ModuleNotFoundError: No module named 'yaml'
"""

PYTEST_OUTPUT = """FAIL test_discount_never_goes_below_zero: AssertionError:

    def test_discount_never_goes_below_zero():
>       assert apply_discount(100.0, 150.0) == 0.0
E       assert -50.0 == 0.0
E        +  where -50.0 = apply_discount(100.0, 150.0)

test_candidate.py:3: AssertionError
"""


class TestExceptionLineSurvives(unittest.TestCase):
    """Defect 68. The answer is on the last line, so the last line matters."""

    def test_exception_type_and_message_are_kept(self):
        out = _excerpt(TRACEBACK)
        self.assertIn("ModuleNotFoundError", out)
        self.assertIn("No module named 'yaml'", out)

    def test_first_line_is_kept(self):
        out = _excerpt(TRACEBACK)
        self.assertIn("COLLECTION ERROR", out)

    def test_frame_locations_are_kept(self):
        out = _excerpt(TRACEBACK)
        self.assertIn("_minirunner.py", out)

    def test_a_long_excerpt_is_elided_in_the_middle_not_the_end(self):
        long_text = chr(10).join(
            [f"frame {n}" for n in range(60)] + ["ValueError: the actual cause"])
        out = _excerpt(long_text)
        self.assertIn("ValueError: the actual cause", out)
        self.assertIn("lines omitted", out)
        self.assertIn("frame 0", out)


class TestSourceEchoNeverSurvives(unittest.TestCase):
    """Defect 70. Telemetry says where and why, never what the code was."""

    def test_traceback_source_echo_is_elided(self):
        out = _excerpt(TRACEBACK)
        self.assertNotIn("apply_discount(100.0, 150.0)", out)
        self.assertNotIn("assert apply_discount", out)
        self.assertNotIn("module = _load(path)", out)

    def test_pytest_echo_forms_are_elided(self):
        out = _excerpt(PYTEST_OUTPUT)
        self.assertNotIn("apply_discount(100.0, 150.0)", out)
        self.assertNotIn("assert apply_discount", out)

    def test_caret_rules_are_dropped(self):
        out = _excerpt(TRACEBACK)
        self.assertNotIn("^^^^", out)

    def test_runs_of_elided_source_collapse(self):
        text = chr(10).join(["Traceback (most recent call last):",
                             "    one = 1", "    two = 2", "    three = 3",
                             "RuntimeError: boom"])
        kept = _strip_source_echo(text.splitlines())
        self.assertEqual(kept.count("    <source elided>"), 1)
        self.assertIn("RuntimeError: boom", kept)

    def test_an_empty_excerpt_stays_empty(self):
        self.assertEqual(_excerpt(""), "")


if __name__ == "__main__":
    unittest.main()
