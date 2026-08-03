"""End-to-end pipeline test with a scripted model.

This runs the real diff parser, the real risk ranker, the real safety gate, the
real git worktrees and the real oracle. Only the model is scripted, because a
model is the one component whose output we must not depend on for a test to be
deterministic.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest.config import Config
from jittest.llm import DryRunLLM, RateLimitedError, TimedOutError
from jittest.pipeline import import_path_for, run
from jittest.report import MARKER, to_markdown, to_terminal

from .helpers import CATCHING_TEST, HARDENING_TEST, FixtureRepo

ASSESSOR_REPLY = json.dumps({
    "verdict": "real_regression",
    "confidence": 0.88,
    "severity": "high",
    "summary": "Removing the clamp lets a discount above 100% return a negative price.",
    "reviewer_question": "Should a discount over 100% still floor the price at zero?",
})


def cfg(**kw) -> Config:
    base = dict(risk_threshold=0.0, max_targets=3, candidates_per_target=2,
                timeout_s=60, reruns=2, ledger_path=".jittest/test-ledger.db")
    base.update(kw)
    return Config(**base)


class TestPipeline(unittest.TestCase):
    def test_finds_and_reports_the_seeded_regression(self):
        llm = DryRunLLM(scripted=[CATCHING_TEST, ASSESSOR_REPLY])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(), llm,
                         pr_title="refactor: round the discounted price",
                         pr_body="Tidy-up only, no behaviour change intended.")

        self.assertEqual(len(report.findings), 1, report.discarded)
        finding = report.findings[0]
        self.assertEqual(finding.target.symbol, "apply_discount")
        self.assertTrue(finding.assessment.should_report)
        self.assertTrue(report.has_regression)
        self.assertEqual(report.cost_usd, 0.0)
        self.assertIn("git checkout", finding.repro_command)

        markdown = to_markdown(report)
        self.assertIn(MARKER, markdown)
        self.assertIn("apply_discount", markdown)
        self.assertIn("Reproduce locally", markdown)
        self.assertIn("apply_discount", to_terminal(report))
        self.assertTrue(json.dumps(report.as_dict()))

    def test_stays_silent_when_the_model_only_writes_hardening_tests(self):
        llm = DryRunLLM(scripted=[HARDENING_TEST])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(), llm)

        self.assertEqual(report.findings, [])
        self.assertFalse(report.has_regression)
        self.assertEqual(to_markdown(report), "",
                         "no proven finding must mean no comment at all")
        self.assertTrue(any("hardening" in k for k in report.discarded))

    def test_declining_costs_nothing_and_says_nothing(self):
        llm = DryRunLLM(scripted=["# NO_CANDIDATE"])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(), llm)
        self.assertEqual(report.findings, [])
        self.assertEqual(report.candidates_generated, 0)
        self.assertEqual(report.discarded.get("model_declined"), 1)
        self.assertEqual(report.discarded.get("model_declined_short_circuit"), 1)


    def test_unsafe_candidates_never_reach_the_oracle(self):
        unsafe = "import socket\n\n\ndef test_x():\n    assert socket\n"
        llm = DryRunLLM(scripted=[unsafe])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(), llm)
        self.assertEqual(report.findings, [])
        self.assertTrue(any(k.startswith("unsafe_or_invalid")
                            for k in report.discarded))

    def test_ignored_paths_are_skipped_before_any_spend(self):
        llm = DryRunLLM(scripted=[CATCHING_TEST, ASSESSOR_REPLY])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(ignore=["calc.py"]), llm)
        self.assertEqual(report.targets_considered, 0)
        self.assertEqual(report.targets_skipped, 1)
        self.assertEqual(llm.usage.calls, 0)


class TestImportPath(unittest.TestCase):
    def test_common_layouts(self):
        self.assertEqual(import_path_for("src/pkg/mod.py"), "pkg.mod")
        self.assertEqual(import_path_for("calc.py"), "calc")
        self.assertEqual(import_path_for("pkg/__init__.py"), "pkg")


class TestCandidateTelemetry(unittest.TestCase):
    """Prove every disposition value is reachable via scripted DryRunLLM."""

    def _cfg(self, **kw):
        base = dict(risk_threshold=0.0, max_targets=1, candidates_per_target=1,
                    timeout_s=60, reruns=2, ledger_path=".jittest/test-tel.db")
        base.update(kw)
        return Config(**base)

    def _dispositions(self, report):
        return [t.disposition for t in report.telemetry]

    def test_model_declined(self):
        llm = DryRunLLM(scripted=["# NO_CANDIDATE"])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        self.assertIn("model_declined", self._dispositions(report))

    def test_parse_failed(self):
        # Valid text but not parseable Python
        llm = DryRunLLM(scripted=["this is not python code at all !!!"])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        self.assertIn("parse_failed", self._dispositions(report))

    def test_safety_rejected(self):
        unsafe = "import socket\n\ndef test_x():\n    assert socket\n"
        llm = DryRunLLM(scripted=[unsafe])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        self.assertIn("safety_rejected", self._dispositions(report))

    def test_head_passed_hardening(self):
        llm = DryRunLLM(scripted=[HARDENING_TEST])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        self.assertIn("head_passed", self._dispositions(report))

    def test_catching(self):
        llm = DryRunLLM(scripted=[CATCHING_TEST, ASSESSOR_REPLY])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm,
                         pr_title="refactor", pr_body="tidy")
        disps = self._dispositions(report)
        self.assertIn("catching", disps)
        # Catching telemetry should have assessor verdict populated
        catching_tel = [t for t in report.telemetry if t.disposition == "catching"]
        self.assertTrue(catching_tel)
        self.assertEqual(catching_tel[0].assessor_verdict, "real_regression")
        self.assertGreater(catching_tel[0].assessor_confidence, 0.0)

    def test_head_uncollectable(self):
        from .helpers import BROKEN_TEST
        llm = DryRunLLM(scripted=[BROKEN_TEST])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        self.assertIn("head_uncollectable", self._dispositions(report))

    def test_head_flaky(self):
        from .helpers import FLAKY_TEST
        llm = DryRunLLM(scripted=[FLAKY_TEST])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         self._cfg(reruns=2), llm)
        self.assertIn("head_flaky", self._dispositions(report))

    def test_telemetry_never_contains_source_code(self):
        llm = DryRunLLM(scripted=[CATCHING_TEST, ASSESSOR_REPLY])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm,
                         pr_title="refactor", pr_body="tidy")
        for tel in report.telemetry:
            d = tel.as_dict()
            # No field should contain the actual test source code body
            for val in d.values():
                if isinstance(val, str):
                    self.assertNotIn("apply_discount(100.0, 150.0)", val)
                    self.assertNotIn("assert apply_discount", val)

    def test_telemetry_jsonl_serialisation(self):
        from jittest.pipeline import CandidateTelemetry
        tel = CandidateTelemetry(
            target_symbol="foo", target_file="bar.py",
            risk_score=0.5, candidate_index=1,
            disposition="catching", head_outcome="fail",
            base_outcome="pass", rerun_agreement=True,
            assessor_verdict="real_regression", assessor_confidence=0.9,
            failure_excerpt="AssertionError",
        )
        import json
        d = json.loads(tel.as_jsonl())
        self.assertEqual(d["disposition"], "catching")
        self.assertEqual(d["target_symbol"], "foo")
        self.assertEqual(d["head_outcome"], "fail")

    def test_report_as_dict_includes_telemetry(self):
        llm = DryRunLLM(scripted=["# NO_CANDIDATE"])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, self._cfg(), llm)
        d = report.as_dict()
        self.assertIn("telemetry", d)
        self.assertTrue(isinstance(d["telemetry"], list))


    def test_model_decline_short_circuits_attempt_loop(self):
        llm = DryRunLLM(scripted=["# NO_CANDIDATE"])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(candidates_per_target=4, max_targets=1), llm)
        self.assertEqual(llm.usage.calls, 1)
        self.assertEqual(report.discarded.get("model_declined"), 1)
        self.assertEqual(report.discarded.get("model_declined_short_circuit"), 3)


    def test_non_python_diff_sets_no_python_in_diff(self):
        llm = DryRunLLM()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)

            (repo / "README.md").write_text("# Hello\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, capture_output=True, check=True)
            b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            (repo / "README.md").write_text("# Hello World\n")
            subprocess.run(["git", "commit", "-am", "head"], cwd=repo, capture_output=True, check=True)
            h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            report = run(repo, b, h, cfg(), llm)
            self.assertEqual(report.diff_status, "no_python_in_diff")

    def test_inverted_range_sets_inverted_range(self):
        llm = DryRunLLM()
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)

            (repo / "app.py").write_text("def v1(): pass\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "v1"], cwd=repo, capture_output=True, check=True)
            h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            (repo / "app.py").write_text("def v1(): pass\ndef v2(): pass\n")
            subprocess.run(["git", "commit", "-am", "v2"], cwd=repo, capture_output=True, check=True)
            b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            # Backwards range: base is v2, head is v1
            report = run(repo, b, h, cfg(), llm)
            self.assertEqual(report.diff_status, "inverted_range")

    def test_rate_limited_disposition(self):
        class ErrorLLM(DryRunLLM):
            def complete(self, system: str, user: str, n: int = 1, temperature: float | None = None) -> list[str]:
                raise RateLimitedError("rate limited by provider")

        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(candidates_per_target=1), ErrorLLM())
        self.assertEqual(report.discarded.get("rate_limited"), 1)
        self.assertEqual(report.telemetry[0].disposition, "rate_limited")

    def test_timed_out_disposition(self):
        class ErrorLLM(DryRunLLM):
            def complete(self, system: str, user: str, n: int = 1, temperature: float | None = None) -> list[str]:
                raise TimedOutError("timed out on provider")

        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(candidates_per_target=1), ErrorLLM())
        self.assertEqual(report.discarded.get("timed_out"), 1)
        self.assertEqual(report.telemetry[0].disposition, "timed_out")


if __name__ == "__main__":
    unittest.main()


