"""Unit tests for risk ranking, config, the safety gate, assessment parsing,
JSON extraction and the ledger.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jittest.assess import Assessment, parse_assessment
from jittest.config import Config, load_config
from jittest.diff import ChangeTarget
from jittest.execute import Outcome
from jittest.ledger import Candidate, Ledger
from jittest.llm import DryRunLLM, extract_json, strip_code_fence
from jittest.pipeline import Finding, Report
from jittest.risk import rank, score_target
from jittest.safety import check_candidate

MONEY = ChangeTarget(
    file_path="billing/calc.py", symbol="apply_discount",
    start_line=1, end_line=9,
    added_lines=[5, 6, 7], removed_lines=[5, 6],
    source_after=(
        "def apply_discount(price, percent):\n"
        "    if percent < 0:\n"
        "        raise ValueError('bad')\n"
        "    discounted = price - (price * percent / 100.0)\n"
        "    return round(discounted, 2)\n"
    ),
    source_before="def apply_discount(price, percent):\n    return max(0.0, price)\n",
)

GETTER = ChangeTarget(
    file_path="pkg/models.py", symbol="Thing.name",
    start_line=1, end_line=3,
    added_lines=[2], removed_lines=[],
    source_after="def name(self):\n    return self._name\n",
    source_before="",
)


class TestRisk(unittest.TestCase):
    def test_money_code_outranks_a_getter(self):
        self.assertGreater(score_target(MONEY).score, score_target(GETTER).score)

    def test_reasons_name_the_domain(self):
        self.assertIn("consequential_domain", score_target(MONEY).reasons)

    def test_scores_stay_in_range(self):
        for t in (MONEY, GETTER):
            self.assertGreaterEqual(score_target(t).score, 0.0)
            self.assertLessEqual(score_target(t).score, 1.0)

    def test_rank_applies_threshold_and_top_k(self):
        self.assertEqual(len(rank([MONEY, GETTER], threshold=0.0, top_k=1)), 1)
        self.assertEqual(rank([MONEY, GETTER], threshold=0.99), [])


class TestConfig(unittest.TestCase):
    def test_defaults_ignore_generated_and_vendored_code(self):
        cfg = Config()
        self.assertTrue(cfg.is_ignored("app/migrations/0001_initial.py"))
        self.assertTrue(cfg.is_ignored("third_party/vendor/lib.py"))
        self.assertFalse(cfg.is_ignored("pkg/calc.py"))

    def test_custom_patterns_match_path_or_basename(self):
        cfg = Config(ignore=["legacy/*", "*_generated.py"])
        self.assertTrue(cfg.is_ignored("legacy/thing.py"))
        self.assertTrue(cfg.is_ignored("pkg/models_generated.py"))
        self.assertFalse(cfg.is_ignored("pkg/models.py"))

    def test_toml_then_overrides_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".jittest.toml").write_text(
                "max_targets = 9\nrisk_threshold = 0.5\n", encoding="utf-8")
            cfg = load_config(repo, overrides={"max_targets": 2})
            self.assertEqual(cfg.max_targets, 2)      # CLI beats file
            self.assertEqual(cfg.risk_threshold, 0.5)  # file beats default

    def test_jittestignore_is_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".jittestignore").write_text(
                "# comment\nscripts/*\n", encoding="utf-8")
            self.assertTrue(load_config(repo).is_ignored("scripts/run.py"))


class TestSafety(unittest.TestCase):
    def test_accepts_an_ordinary_test(self):
        check = check_candidate(
            "from calc import f\n\n\ndef test_x():\n    assert f(1) == 2\n")
        self.assertTrue(check.ok, check.reason)

    def test_rejects_dangerous_or_useless_code(self):
        cases = {
            "network": "import requests\n\n\ndef test_x():\n    assert requests\n",
            "shell": "import subprocess\n\n\ndef test_x():\n    assert 1\n",
            "eval": "def test_x():\n    assert eval('1') == 1\n",
            "tautology": "def test_x():\n    assert True\n",
            "no assert": "def test_x():\n    pass\n",
            "no test": "def helper():\n    assert 1 == 1\n",
            "syntax": "def test_x(:\n",
            "empty": "   ",
        }
        for label, code in cases.items():
            self.assertFalse(check_candidate(code).ok, label)

    def test_warns_about_secrets_without_blocking(self):
        check = check_candidate(
            "import os\n\n\ndef test_x():\n    assert os.getenv('API_KEY') is None\n")
        self.assertTrue(check.ok)
        self.assertTrue(check.warnings)


class TestAssessment(unittest.TestCase):
    def test_reports_only_confident_regressions(self):
        self.assertTrue(Assessment("real_regression", 0.9).should_report)
        self.assertFalse(Assessment("real_regression", 0.5).should_report)
        self.assertFalse(Assessment("intended_change", 0.99).should_report)

    def test_parsing_is_forgiving_but_fails_closed(self):
        a = parse_assessment({"verdict": "real_regression", "confidence": 85,
                              "severity": "high", "summary": "clamp removed"})
        self.assertEqual(a.confidence, 0.85)
        self.assertTrue(a.should_report)

        self.assertEqual(parse_assessment({"verdict": "nonsense"}).verdict, "unclear")
        self.assertFalse(parse_assessment(None).should_report)
        self.assertFalse(parse_assessment({"verdict": "unclear",
                                           "confidence": 0.99}).should_report)


class TestJsonExtraction(unittest.TestCase):
    def test_survives_prose_fences_and_braces_in_strings(self):
        payload = {"verdict": "unclear", "summary": "uses {braces} inside"}
        blob = "Sure!\n```json\n" + json.dumps(payload) + "\n```\nHope that helps."
        self.assertEqual(extract_json(blob), payload)

    def test_returns_none_when_there_is_no_object(self):
        self.assertIsNone(extract_json("no json here"))
        self.assertIsNone(extract_json(""))

    def test_strip_code_fence(self):
        self.assertEqual(strip_code_fence("```python\nx = 1\n```"), "x = 1")
        self.assertEqual(strip_code_fence("x = 1"), "x = 1")


class TestDryRunLLM(unittest.TestCase):
    def test_scripted_then_sticky_and_free(self):
        llm = DryRunLLM(scripted=["first", "second"])
        self.assertEqual(llm.complete("s", "u")[0], "first")
        self.assertEqual(llm.complete("s", "u")[0], "second")
        self.assertEqual(llm.complete("s", "u")[0], "second")
        self.assertEqual(llm.usage.cost_usd, 0.0)


class TestLedger(unittest.TestCase):
    def _candidate(self, **kw) -> Candidate:
        base = dict(repo="acme", pr="42", file_path="billing/calc.py",
                    symbol="apply_discount", test_code="def test_x():\n    assert 1\n",
                    oracle_catching=True, reported=True, cost_usd=0.02)
        base.update(kw)
        return Candidate(**base)

    def test_record_stats_outcomes_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            with Ledger(db) as ledger:
                cid = ledger.record(self._candidate())
                ledger.record(self._candidate(
                    test_code="def test_y():\n    assert 2\n",
                    oracle_catching=False, reported=False))

                stats = ledger.stats()
                self.assertEqual(stats["candidates"], 2)
                self.assertEqual(stats["catching"], 1)
                self.assertIsNone(stats["true_positive_rate"])

                ledger.mark_outcome(cid, "fixed_code", note="author pushed a fix")
                self.assertEqual(ledger.stats()["true_positive_rate"], 1.0)

                with self.assertRaises(ValueError):
                    ledger.mark_outcome(cid, "not_a_real_outcome")

                out = Path(tmp) / "corpus.jsonl"
                self.assertEqual(ledger.export_jsonl(out), 2)
                first = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
                self.assertNotIn("test_code", first)
                self.assertNotEqual(first["repo"], "acme")
                self.assertEqual(first["symbol"], "redacted")

    def test_outcome_by_hash(self):
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "l.db") as ledger:
            cand = self._candidate()
            ledger.record(cand)
            self.assertEqual(
                ledger.mark_outcome_by_hash(cand.test_hash, "kept_test"), 1)

    # --- Outcome StrEnum regression tests ---
    # These tests would have caught the UP042 "fix" that changed
    # Outcome(str, Enum) -> Outcome(Enum), removing string behaviour.

    def test_outcome_json_serialization(self):
        """json.dumps of a dict containing an Outcome member must succeed
        and yield the expected string value, not '"Outcome.PASS"'."""
        d = {"outcome": Outcome.PASS}
        result = json.dumps(d)
        self.assertEqual(json.loads(result)["outcome"], "pass")

    def test_outcome_equals_string(self):
        """Outcome.PASS == 'pass' must hold - the codebase relies on
        string comparison semantics."""
        self.assertEqual(Outcome.PASS, "pass")
        self.assertEqual(Outcome.FAIL, "fail")
        self.assertEqual(Outcome.ERROR, "error")
        self.assertEqual(Outcome.TIMEOUT, "timeout")

    def test_report_as_dict_with_outcomes_json_roundtrip(self):
        """A Report containing outcomes must round-trip through as_dict()
        and json.dumps without raising."""
        target = ChangeTarget(file_path="calc.py", symbol="add",
                              start_line=1, end_line=10,
                              added_lines=[5], removed_lines=[],
                              source_after="def add(a,b): return a+b",
                              source_before="def add(a,b): return a-b")
        finding = Finding(
            target=target,
            test_code="def test_add(): assert add(1,1)==2",
            oracle_reason="test fails on head, passes on base",
            failure_excerpt="AssertionError",
            assessment=Assessment(verdict="real_regression", confidence=0.9,
                                  severity="medium", summary="regression detected",
                                  reviewer_question="did you change add()?"),
            risk_score=0.8,
            risk_reasons=["new branch added"],
            repro_command="pytest test_add.py",
        )
        report = Report(
            repo="test", base="abc123", head="def456",
            model="test-model",
            findings=[finding], latent_findings=[],
            targets_considered=1, targets_skipped=0,
            candidates_generated=1, cost_usd=0.01, duration_s=1.0,
            discarded={}, errors=[],
        )
        d = report.as_dict()
        # Must not raise - if Outcome is plain Enum, json.dumps will
        # raise TypeError: Object of type Outcome is not JSON serializable
        # only if Outcome appears in the dict. Currently outcomes are not
        # in as_dict(), but if they ever are, this test will catch it.
        # The key test is that json.dumps succeeds.
        result = json.dumps(d)
        parsed = json.loads(result)
        self.assertEqual(parsed["findings"][0]["assessment"]["verdict"],
                         "real_regression")

    def test_ledger_export_jsonl_validates_with_outcomes(self):
        """The ledger's export_jsonl output must be valid JSON when
        outcomes are present. The ledger stores oracle_catching as int
        and oracle_reason as str, so this tests the full pipeline path."""
        with tempfile.TemporaryDirectory() as tmp, Ledger(Path(tmp) / "l.db") as ledger:
            cand = self._candidate()
            cand.oracle_catching = True
            cand.oracle_reason = "test fails on head, passes on base"
            cand.assess_verdict = "real_regression"
            ledger.record(cand)
            ledger.mark_outcome_by_hash(cand.test_hash, "fixed_code")

            out = Path(tmp) / "corpus.jsonl"
            count = ledger.export_jsonl(out)
            self.assertEqual(count, 1)

            # Every line must be valid JSON
            for line in out.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)  # raises if invalid
                self.assertIn("oracle_catching", rec)
                self.assertEqual(rec["human_outcome"], "fixed_code")


if __name__ == "__main__":
    unittest.main()
