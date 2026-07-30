"""The target funnel must add up, in the report and in the eval gate.

The targets_skipped finding (evaluation integrity). A Report counted only two
kinds of target: skipped (dropped by an ignore rule) and considered (passed the
risk ranking). Targets dropped BY the ranking - below the threshold or beyond
top_k - were tracked nowhere, so a report could read "3 changed symbol(s)
analysed" whether 3 symbols changed or 300 changed with 297 filtered out. A
number the reader cannot reconstruct is a number that can lie.

In the eval the same gap let a filtered bug hide: diff_status "ok", zero
candidates, zero model requests, classify() said not_measured - the same label
as an empty diff, a property of the revision pair. A ranker that silently
dropped the buggy symbol was indistinguishable from a pair with nothing to
test. "filtered" is now its own status: it stays in the headline denominator
as a non-catch, counts against the completion floor, and is named in the
summary and by the gate.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jittest.pipeline import Report, run
from jittest.report import to_terminal


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "run_bugsinpy", Path(__file__).resolve().parent.parent
        / "eval" / "run_bugsinpy.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_gate():
    spec = importlib.util.spec_from_file_location(
        "assert_measured", Path(__file__).resolve().parent.parent
        / "eval" / "assert_measured.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


BASE = (
    "def discount(price, pct):\n"
    "    return price - (price * pct / 100.0)\n"
)
HEAD = BASE.replace("/ 100.0", "/ 10.0")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    for var in ("GIT_DIR", "GIT_WORK_TREE"):
        env.pop(var, None)
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, errors="replace",
                          timeout=120)


def _repo(root: Path, base: str = BASE, head: str = HEAD) -> tuple[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    (root / "calc.py").write_text(base)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "calc.py").write_text(head)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "head")
    head_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return base_sha, head_sha


def _report(repo: Path, base: str, head: str, **overrides) -> Report:
    from jittest.config import load_config
    from jittest.llm import DryRunLLM
    cfg = load_config(repo, overrides=overrides)
    llm = DryRunLLM(scripted=["# NO_CANDIDATE"])
    return run(repo, base, head, cfg, llm)


class ReportFunnel(unittest.TestCase):
    def test_extracted_equals_considered_plus_filtered_plus_skipped(self) -> None:
        report = Report(repo="r", base="b", head="h", model="m",
                        targets_considered=2, targets_skipped=1,
                        targets_filtered=5)
        extracted = (report.targets_considered + report.targets_filtered
                     + report.targets_skipped)
        self.assertEqual(extracted, 8)
        self.assertEqual(report.as_dict()["targets_filtered"], 5)

    def test_targets_filtered_defaults_to_zero(self) -> None:
        report = Report(repo="r", base="b", head="h", model="m")
        self.assertEqual(report.targets_filtered, 0)
        self.assertIn("targets_filtered", report.as_dict())

    def test_terminal_line_discloses_the_funnel(self) -> None:
        report = Report(repo="r", base="b1234567", head="h1234567", model="m",
                        targets_considered=1, targets_skipped=1,
                        targets_filtered=3)
        text = to_terminal(report)
        self.assertIn("1/5", text)
        self.assertIn("3 below threshold", text)
        self.assertIn("1 ignored", text)


class PipelineCountsTheFilterDrop(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.base, self.head = _repo(self.repo)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_below_threshold_targets_are_counted_as_filtered(self) -> None:
        report = _report(self.repo, self.base, self.head, risk_threshold=0.99)
        self.assertEqual(report.targets_considered, 0)
        self.assertGreaterEqual(report.targets_filtered, 1)
        self.assertEqual(report.model_requests, 0)

    def test_ignored_targets_are_counted_as_skipped_not_filtered(self) -> None:
        report = _report(self.repo, self.base, self.head,
                         ignore=["calc.py"], risk_threshold=0.99)
        self.assertEqual(report.targets_considered, 0)
        self.assertEqual(report.targets_filtered, 0)
        self.assertGreaterEqual(report.targets_skipped, 1)

    def test_an_unfiltered_run_has_no_filtered_targets(self) -> None:
        report = _report(self.repo, self.base, self.head, risk_threshold=0.0)
        self.assertEqual(report.targets_filtered, 0)
        self.assertGreaterEqual(report.targets_considered, 1)


class ClassifyNamesTheFilteredRun(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bugs = _load_eval()

    def test_filtered_is_its_own_status(self) -> None:
        self.assertEqual(
            self.bugs.classify(0, 0, "ok", targets_extracted=3,
                               targets_considered=0),
            "filtered")

    def test_empty_diff_is_still_not_measured(self) -> None:
        self.assertEqual(
            self.bugs.classify(0, 0, "empty", targets_extracted=0,
                               targets_considered=0),
            "not_measured")

    def test_nothing_extracted_is_still_not_measured(self) -> None:
        """A diff with no Python symbols has nothing to filter or to test."""
        self.assertEqual(
            self.bugs.classify(0, 0, "ok", targets_extracted=0,
                               targets_considered=0),
            "not_measured")

    def test_a_measured_run_is_unaffected(self) -> None:
        self.assertEqual(self.bugs.classify(2, 1, "ok", 3, 2), "caught")
        self.assertEqual(self.bugs.classify(2, 0, "ok", 3, 2), "missed")

    def test_git_failure_still_wins_over_everything(self) -> None:
        self.assertEqual(
            self.bugs.classify(0, 0, "git_failed", targets_extracted=4,
                               targets_considered=0),
            "git_failed")

    def test_the_old_two_argument_call_still_works(self) -> None:
        self.assertEqual(self.bugs.classify(0, 0), "not_measured")
        self.assertEqual(self.bugs.classify(2, 1), "caught")


class SummaryCountsFilteredByName(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bugs = _load_eval()

    def _row(self, bug_id: str, status: str, requests: int,
             catching: int = 0) -> object:
        return self.bugs.BugResult(
            project="p", bug_id=bug_id, status=status,
            model_requests=requests, catching_candidates=catching)

    def test_filtered_is_counted_and_stays_in_the_headline_denominator(self) -> None:
        summary = self.bugs.summarize([
            self._row("1", "caught", 3, catching=1),
            self._row("2", "filtered", 0),
            self._row("3", "missed", 2),
        ])
        self.assertEqual(summary["bugs_filtered"], 1)
        self.assertEqual(summary["bugs_attempted"], 3)
        self.assertEqual(summary["bugs_eligible"], 3)
        # One catch over three eligible bugs: the filtered bug is a non-catch,
        # never silently removed from the denominator.
        self.assertEqual(summary["catch_rate"], round(1 / 3, 3))

    def test_filtered_counts_against_the_completion_floor(self) -> None:
        """A ranker that filters everything cannot keep the gate green."""
        summary = self.bugs.summarize([
            self._row("1", "filtered", 0),
            self._row("2", "filtered", 0),
        ])
        self.assertEqual(summary["bugs_measured"], 0)
        self.assertEqual(summary["completion_rate"], 0.0)


class GateCrossChecksFiltered(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = _load_gate()

    def _payload(self, filtered_summary: int, filtered_rows: int) -> dict:
        # Four measured bugs keep completion at exactly the 80% floor when a
        # filtered bug is added, so the GOOD payload cannot trip the floor.
        rows = [{"status": "caught", "model_requests": 2} for _ in range(4)]
        rows += [{"status": "filtered", "model_requests": 0}
                 for _ in range(filtered_rows)]
        return {
            "summary": {
                "bugs_attempted": 4 + filtered_rows,
                "bugs_eligible": 4 + filtered_rows,
                "bugs_measured": 4,
                "bugs_not_measured": 0,
                "bugs_git_failed": 0,
                "bugs_filtered": filtered_summary,
                "model_requests_total": 8,
                "catch_rate": round(4 / (4 + filtered_rows), 3),
            },
            "results": rows,
        }

    def _run_gate(self, payload: dict) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.json"
            import json
            path.write_text(json.dumps(payload))
            return self.gate.main(["assert_measured.py", str(path)])

    def test_a_consistent_filtered_count_passes(self) -> None:
        self.assertEqual(self._run_gate(self._payload(1, 1)), 0)

    def test_a_lying_filtered_count_fails(self) -> None:
        self.assertEqual(self._run_gate(self._payload(0, 1)), 1)

    def test_a_missing_filtered_count_fails_closed(self) -> None:
        payload = self._payload(1, 1)
        del payload["summary"]["bugs_filtered"]
        self.assertEqual(self._run_gate(payload), 1)


if __name__ == "__main__":
    unittest.main()
