"""A run that analysed nothing must not look like a run that found nothing.

This is the same rule `diff_status` already applies one step earlier, where
"git failed" was split from "the diff was empty". The gap this file closes is
the next step down: git succeeded, the diff was real, and then every changed
symbol was removed - either by an ignore pattern or by the risk threshold.

Before this change both outcomes produced a byte-identical report: no findings,
no errors, exit 0, and a green check on the pull request. The two causes are
also the two most likely to be wrong silently. The ignore list is usually
inherited from the defaults and never read; the risk threshold is a number
nobody revisits after the first week. A team can run jittest for a month,
receive nothing, and conclude the tool found no regressions, when in fact it
never looked at a single line.

That failure is worse than a crash. A crash gets fixed. Silent success gets
trusted, and the eval numbers computed from these runs would be arithmetic
over a denominator that includes runs where nothing was attempted - the exact
integrity defect that `bugs_eligible` exists to prevent on the eval side.
"""
from __future__ import annotations

import json
import unittest

from jittest.config import Config
from jittest.llm import DryRunLLM
from jittest.pipeline import run

from .helpers import FixtureRepo


def cfg(**kw) -> Config:
    base = dict(risk_threshold=0.0, max_targets=3, candidates_per_target=1,
                timeout_s=60, reruns=2, ledger_path=".jittest/test-ledger.db")
    base.update(kw)
    return Config(**base)


class NothingAnalysed(unittest.TestCase):
    def test_all_targets_ignored_is_named(self):
        llm = DryRunLLM(scripted=[])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(ignore=["*.py"]), llm)

        self.assertEqual(report.diff_status, "all_targets_ignored")
        self.assertGreater(report.targets_skipped, 0)
        self.assertEqual(report.targets_considered, 0)
        self.assertTrue(report.errors, "the cause must be stated, not implied")
        self.assertTrue(any("ignore" in e for e in report.errors))
        # No model was consulted, so no cost may be claimed either way.
        self.assertEqual(report.model_requests, 0)

    def test_below_risk_threshold_is_named_and_actionable(self):
        llm = DryRunLLM(scripted=[])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(risk_threshold=1.0), llm)

        self.assertEqual(report.diff_status, "below_risk_threshold")
        self.assertEqual(report.targets_considered, 0)
        self.assertEqual(report.targets_skipped, 0,
                         "nothing was ignored; the threshold did this")
        self.assertTrue(report.errors)
        joined = " ".join(report.errors)
        # An operator reading this must know which knob to turn.
        self.assertIn("risk_threshold", joined)

    def test_a_normal_run_keeps_saying_ok(self):
        """The new statuses must not fire on the healthy path."""
        from .helpers import CATCHING_TEST
        assessor = json.dumps({
            "verdict": "real_regression", "confidence": 0.9,
            "severity": "high", "summary": "clamp removed",
            "reviewer_question": "intended?",
        })
        llm = DryRunLLM(scripted=[CATCHING_TEST, assessor])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head, cfg(), llm)
        self.assertEqual(report.diff_status, "ok")

    def test_status_survives_serialisation(self):
        """The eval harness reads the JSON, not the dataclass."""
        llm = DryRunLLM(scripted=[])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(ignore=["*.py"]), llm)
        payload = json.loads(json.dumps(report.as_dict()))
        self.assertEqual(payload["diff_status"], "all_targets_ignored")


class SandboxIsRecorded(unittest.TestCase):
    """Whether candidates were confined is a fact about the run, so it belongs
    in the run's own record rather than in the operator's assumptions."""

    def test_report_states_the_isolation_actually_used(self):
        from .helpers import CATCHING_TEST
        assessor = json.dumps({
            "verdict": "real_regression", "confidence": 0.9,
            "severity": "high", "summary": "clamp removed",
            "reviewer_question": "intended?",
        })
        llm = DryRunLLM(scripted=[CATCHING_TEST, assessor])
        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(sandbox_mode="off"), llm)

        payload = json.loads(json.dumps(report.as_dict()))
        self.assertIn("sandbox", payload)
        self.assertFalse(payload["sandbox"]["isolated"])
        self.assertEqual(payload["sandbox"]["backend"], "none")
        # An unconfined run must carry the warning into the report the human
        # actually reads, not only into the JSON a machine parses.
        self.assertTrue(report.errors)

    def test_required_mode_refuses_the_run_rather_than_running_bare(self):
        """Fail closed, and say so in the report instead of raising into CI."""
        from jittest import sandbox as S

        from .helpers import CATCHING_TEST
        original = S.detect_backend
        S.detect_backend = lambda preferred="": "none"
        try:
            llm = DryRunLLM(scripted=[CATCHING_TEST])
            with FixtureRepo() as repo:
                report = run(repo.path, repo.base, repo.head,
                             cfg(sandbox_mode="required"), llm)
        finally:
            S.detect_backend = original

        self.assertEqual(report.diff_status, "sandbox_unavailable")
        self.assertEqual(report.findings, [])
        self.assertTrue(report.errors)
        self.assertEqual(report.model_requests, 0,
                         "refusing must happen before any money is spent")


if __name__ == "__main__":
    unittest.main()
