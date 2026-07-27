"""Regression tests for Defect 31: untrusted text was rendered verbatim.

Everything jittest puts in a PR comment other than its own boilerplate comes
from one of two untrusted places: a language model, or captured pytest output
from code under test. The assessor reads the PR title and body, which on a
public repository any stranger can write.

The report is upserted by searching existing comments for a single literal
marker. Premortem 2 rendered an assessment whose summary contained that marker
and produced a comment with six of them. Consequences, in order of seriousness:

  1. `upsert_pr_comment` can no longer identify its own comment, so a crafted PR
     body could make jittest edit an unrelated comment or orphan its own.
  2. `-->` inside injected text closes the HTML comment early, and `<!--` opens
     a new one, letting injected content comment out the real findings.
  3. Backticks inside a failure excerpt escape the code fence and let injected
     text render as markdown.

The invariant locked in here: a rendered report contains exactly one marker, no
matter what the model or the code under test emitted.
"""
import unittest

from jittest.assess import Assessment
from jittest.diff import ChangeTarget
from jittest.pipeline import Finding, Report
from jittest.report import MARKER, to_markdown

ATTACKS = {
    "marker": MARKER,
    "marker-repeated": MARKER * 4,
    "comment-close": "text --> visible <!-- hidden",
    "backticks": "```\nescaped\n```",
    "long-backtick-run": "`````\nescaped\n`````",
    "details-close": "</details></details><script>alert(1)</script>",
    "newlines-in-quote": "line one\nline two\nline three",
    "very-long": "x" * 20000,
}


def _finding(text):
    target = ChangeTarget(
        file_path="money.py", symbol="apply_discount", start_line=1, end_line=4,
        added_lines=[text], removed_lines=[text], source_after=text,
        source_before=text,
    )
    assessment = Assessment(
        verdict="real_regression", confidence=0.91, severity="high",
        summary=text, reviewer_question=text, raw=text,
    )
    return Finding(
        target=target,
        test_code="def test_x():\n    assert True\n",
        oracle_reason="catching: passes on base, fails on head",
        failure_excerpt=text,
        assessment=assessment,
        risk_score=0.52,
        risk_reasons=[text],
        repro_command="git checkout head && pytest x.py",
    )


def _report(findings, errors=None):
    return Report(
        repo="acme/app", base="a" * 40, head="b" * 40, model="test-model",
        findings=findings, errors=errors or [],
    )


class TestMarkerCannotBeInjected(unittest.TestCase):
    def test_every_attack_yields_exactly_one_marker(self):
        for name, text in ATTACKS.items():
            with self.subTest(attack=name):
                md = to_markdown(_report([_finding(text)]))
                self.assertEqual(
                    md.count(MARKER), 1,
                    f"{name}: marker count {md.count(MARKER)} would break upsert",
                )

    def test_marker_is_the_first_line(self):
        md = to_markdown(_report([_finding(MARKER)]))
        self.assertTrue(md.startswith(MARKER))

    def test_injected_marker_is_visibly_neutralised(self):
        md = to_markdown(_report([_finding(MARKER)]))
        self.assertIn("marker removed", md)

    def test_errors_list_cannot_inject_a_marker(self):
        md = to_markdown(_report([_finding("clean")], errors=[MARKER, MARKER]))
        self.assertEqual(md.count(MARKER), 1)

    def test_low_confidence_section_cannot_inject_a_marker(self):
        low = _finding(MARKER)
        low.assessment.confidence = 0.10
        low.assessment.verdict = "unclear"
        md = to_markdown(_report([low]))
        self.assertEqual(md.count(MARKER), 1)


class TestHtmlAndFenceContainment(unittest.TestCase):
    def test_html_comment_delimiters_are_escaped(self):
        md = to_markdown(_report([_finding("a --> b <!-- c")]))
        # The only raw delimiters left belong to jittest's own marker.
        self.assertEqual(md.count("<!--"), 1)
        self.assertEqual(md.count("-->"), 1)
        self.assertIn("&lt;!--", md)
        self.assertIn("--&gt;", md)

    def test_backticks_cannot_escape_the_fence(self):
        md = to_markdown(_report([_finding("```\nnot markdown\n```")]))
        # Fences are widened, so no line is a bare three-backtick terminator
        # sitting inside what should still be fenced output.
        self.assertIn("````", md)

    def test_reviewer_question_stays_on_one_quoted_line(self):
        md = to_markdown(_report([_finding("one\ntwo\nthree")]))
        quoted = [ln for ln in md.splitlines() if ln.startswith("> ")]
        self.assertTrue(quoted)
        for line in quoted:
            self.assertNotIn("\n", line)
        self.assertTrue(any("one two three" in ln for ln in quoted))

    def test_oversized_text_is_truncated(self):
        md = to_markdown(_report([_finding("x" * 20000)]))
        self.assertIn("(truncated)", md)
        self.assertLess(len(md), 20000)


class TestNormalReportsAreUnchanged(unittest.TestCase):
    """Sanitisation must not damage an ordinary, well-behaved finding."""

    def test_plain_summary_survives_intact(self):
        f = _finding("clean")
        f.assessment.summary = (
            "Removing the clamp lets a discount above 100% return a negative price.")
        f.assessment.reviewer_question = (
            "Should a discount over 100% still floor the price at zero?")
        f.failure_excerpt = "AssertionError: assert -50.0 == 0.0"
        md = to_markdown(_report([f]))
        self.assertIn("return a negative price", md)
        self.assertIn("floor the price at zero", md)
        self.assertIn("AssertionError", md)
        self.assertIn("```python", md)
        self.assertEqual(md.count(MARKER), 1)

    def test_empty_report_is_still_silent(self):
        self.assertEqual(to_markdown(_report([])), "")


if __name__ == "__main__":
    unittest.main()
