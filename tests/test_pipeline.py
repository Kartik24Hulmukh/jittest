"""End-to-end pipeline test with a scripted model.

This runs the real diff parser, the real risk ranker, the real safety gate, the
real git worktrees and the real oracle. Only the model is scripted, because a
model is the one component whose output we must not depend on for a test to be
deterministic.
"""
from __future__ import annotations

import json
import unittest

from jittest.config import Config
from jittest.llm import DryRunLLM
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
        self.assertEqual(report.discarded.get("model_declined"), 2)

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


if __name__ == "__main__":
    unittest.main()
