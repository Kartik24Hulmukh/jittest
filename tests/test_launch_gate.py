"""Regression tests for scripts/launch_gate.py (launch go/no-go aggregator)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("launch_gate", ROOT / "scripts" / "launch_gate.py")
assert SPEC is not None and SPEC.loader is not None
launch_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launch_gate)

GOOD_SOAK = {
    "leak_slope_limit_kib_per_1k_ops": 1.0,
    "leak_slope_kib_per_1k_ops": 0.01,
    "leak_suspected": False,
    "errors": 0,
    "distinct_digests": 1,
    "deterministic": True,
    "total_ops": 100_000,
    "seed": 20260916,
}


class SoakEvidenceContract(unittest.TestCase):
    def test_committed_evidence_satisfies_contract(self):
        doc = json.loads((ROOT / launch_gate.SOAK_EVIDENCE).read_text(encoding="utf-8"))
        result = launch_gate.check_soak_evidence(doc)
        self.assertTrue(result["ok"], result["problems"])

    def test_good_document_passes(self):
        self.assertTrue(launch_gate.check_soak_evidence(GOOD_SOAK)["ok"])

    def test_leak_over_limit_fails(self):
        doc = dict(GOOD_SOAK, leak_slope_kib_per_1k_ops=1.5)
        result = launch_gate.check_soak_evidence(doc)
        self.assertFalse(result["ok"])
        self.assertTrue(any("exceeds limit" in p for p in result["problems"]))

    def test_errors_or_nondeterminism_fail(self):
        self.assertFalse(launch_gate.check_soak_evidence(dict(GOOD_SOAK, errors=1))["ok"])
        self.assertFalse(launch_gate.check_soak_evidence(dict(GOOD_SOAK, distinct_digests=2))["ok"])
        self.assertFalse(
            launch_gate.check_soak_evidence(dict(GOOD_SOAK, leak_suspected=True))["ok"]
        )

    def test_missing_fields_fail_closed(self):
        self.assertFalse(launch_gate.check_soak_evidence({})["ok"])

    def test_evidence_cannot_relax_policy_threshold(self):
        for limit in [1000, float("inf"), float("nan"), True, "1.0", None, -1]:
            with self.subTest(limit=limit):
                doc = dict(GOOD_SOAK, leak_slope_limit_kib_per_1k_ops=limit)
                self.assertFalse(launch_gate.check_soak_evidence(doc)["ok"])
        self.assertFalse(
            launch_gate.check_soak_evidence(
                dict(GOOD_SOAK, leak_slope_limit_kib_per_1k_ops=1000, leak_slope_kib_per_1k_ops=999)
            )["ok"]
        )

    def test_nonfinite_and_boolean_slopes_refuse(self):
        for slope in [float("nan"), float("inf"), -float("inf"), False, True, "0"]:
            with self.subTest(slope=slope):
                self.assertFalse(
                    launch_gate.check_soak_evidence(
                        dict(GOOD_SOAK, leak_slope_kib_per_1k_ops=slope)
                    )["ok"]
                )

    def test_huge_json_integer_refuses_without_float_overflow(self):
        for field in ["leak_slope_limit_kib_per_1k_ops", "leak_slope_kib_per_1k_ops"]:
            with self.subTest(field=field):
                doc = json.loads(json.dumps(dict(GOOD_SOAK, **{field: 10**400})))
                self.assertFalse(launch_gate.check_soak_evidence(doc)["ok"])

    def test_malformed_counts_and_top_level_refuse_without_crash(self):
        for doc in [None, [], "bad", 1]:
            self.assertFalse(launch_gate.check_soak_evidence(doc)["ok"])
        for field, values in {
            "errors": [False, "0", None],
            "distinct_digests": [True, "1", None],
            "total_ops": ["100000", None, float("inf"), True],
            "seed": ["20260916", 20260916.0, None],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.assertFalse(
                        launch_gate.check_soak_evidence(dict(GOOD_SOAK, **{field: value}))["ok"]
                    )


class ReceiptClassification(unittest.TestCase):
    def test_regular_receipt_must_be_valid(self):
        good = {"signature_valid": True, "valid": True, "semantic_valid": True}
        self.assertTrue(launch_gate.classify_receipt("x.json", 0, good)["ok"])
        self.assertFalse(launch_gate.classify_receipt("x.json", 5, dict(good, valid=False))["ok"])

    def test_known_refused_receipt_must_stay_refused(self):
        # The allowlist is empty since the #206 regeneration; exercise the
        # mechanism with a synthetic pin so a future documented refusal still works.
        rel = "docs/evidence/quadrants/synthetic_refused.json"
        refused = {"signature_valid": True, "valid": False, "semantic_valid": False}
        accepted = {"signature_valid": True, "valid": True, "semantic_valid": True}
        with patch.dict(launch_gate.KNOWN_REFUSED_RECEIPTS, {rel: "semantic_invalid"}):
            self.assertTrue(launch_gate.classify_receipt(rel, 5, refused)["ok"])
            # If someone silently makes it pass, the gate must notice.
            self.assertFalse(launch_gate.classify_receipt(rel, 0, accepted)["ok"])
            # A tampered signature is never acceptable, refused or not.
            self.assertFalse(
                launch_gate.classify_receipt(rel, 5, dict(refused, signature_valid=False))["ok"]
            )

    def test_regenerated_showcase_receipt_is_expected_valid(self):
        # Issue #206: the non_discriminating showcase receipt was regenerated as a
        # schema 2.1 receipt (base PASS / head PASS) and must no longer be pinned.
        rel = "docs/evidence/quadrants/non_discriminating_evidence.json"
        self.assertNotIn(rel, launch_gate.KNOWN_REFUSED_RECEIPTS)
        accepted = {"signature_valid": True, "valid": True, "semantic_valid": True}
        self.assertTrue(launch_gate.classify_receipt(rel, 0, accepted)["ok"])
        refused = {"signature_valid": True, "valid": False, "semantic_valid": False}
        self.assertFalse(launch_gate.classify_receipt(rel, 5, refused)["ok"])
        receipt = json.loads((launch_gate.ROOT / rel).read_text(encoding="utf-8"))
        self.assertEqual(receipt["schema_version"], "2.1")
        self.assertEqual(receipt["verdict"], "non_discriminating")
        self.assertEqual(receipt["base_execution"]["outcome"], "PASS")
        self.assertEqual(receipt["head_execution"]["outcome"], "PASS")


class GaReadyIsDerivedNotDeclared(unittest.TestCase):
    def test_open_blockers_keep_ga_false(self):
        self.assertFalse(launch_gate.derive_ga_ready(launch_gate.GA_BLOCKERS))
        self.assertTrue(launch_gate.derive_ga_ready([]))

    def test_decision_matrix(self):
        ok = {"a": {"ok": True}}
        bad = {"a": {"ok": True}, "b": {"ok": False}}
        self.assertEqual(
            launch_gate.build_report(ok, launch_gate.GA_BLOCKERS)["decision"], "GO_LAUNCH_NOT_GA"
        )
        self.assertEqual(launch_gate.build_report(ok, [])["decision"], "GO_GA")
        self.assertEqual(launch_gate.build_report(bad, [])["decision"], "NO_GO")
        self.assertEqual(
            launch_gate.build_report(bad, launch_gate.GA_BLOCKERS)["decision"], "NO_GO"
        )

    def test_report_digest_is_deterministic_and_excludes_volatile(self):
        gates = {"a": {"ok": True, "detail": ["x"]}}
        r1 = launch_gate.build_report(gates, launch_gate.GA_BLOCKERS)
        r2 = launch_gate.build_report(json.loads(json.dumps(gates)), list(launch_gate.GA_BLOCKERS))
        self.assertEqual(r1["digest"], r2["digest"])
        self.assertNotIn("volatile", r1)

    def test_blockers_reference_real_issue_numbers(self):
        for row in launch_gate.GA_BLOCKERS:
            self.assertIsInstance(row["issue"], int)
            self.assertTrue(row["title"])


class FailClosedLaunchEvidence(unittest.TestCase):
    def test_receipt_flags_must_be_json_booleans(self):
        good = {"signature_valid": True, "valid": True, "semantic_valid": True}
        for field in good:
            for value in ["true", "false", 1, 0, None, [], {}]:
                with self.subTest(field=field, value=value):
                    self.assertFalse(launch_gate.classify_receipt(
                        "x.json", 0, dict(good, **{field: value}))["ok"])

    def test_non_object_receipt_refuses(self):
        for payload in [None, [], "bad", True, 42]:
            self.assertFalse(launch_gate.classify_receipt("x.json", 0, payload)["ok"])

    def test_expected_refusal_requires_explicit_false_and_semantic_exit(self):
        rel = "docs/evidence/quadrants/synthetic_refused.json"
        good = {"signature_valid": True, "valid": False, "semantic_valid": False}
        with patch.dict(launch_gate.KNOWN_REFUSED_RECEIPTS, {rel: "semantic_invalid"}):
            for code in [0, 1, 2, -9]:
                self.assertFalse(launch_gate.classify_receipt(rel, code, good)["ok"])
            for value in [None, "false", 0, True]:
                self.assertFalse(launch_gate.classify_receipt(
                    rel, 5, dict(good, valid=value))["ok"])

    def test_empty_or_truthy_gate_set_never_approves(self):
        for gates in [{}, {"x": {}}, {"x": {"ok": "false"}}, {"x": {"ok": 1}}]:
            self.assertEqual(launch_gate.build_report(gates, [])["decision"], "NO_GO")

    def test_missing_focused_suite_refuses_before_execution(self):
        with (
            patch.object(launch_gate, "FOCUSED_SUITES", ["tests/does_not_exist.py"]),
            patch.object(launch_gate, "_run") as run,
        ):
            result = launch_gate.gate_tests(False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_suites"], ["tests/does_not_exist.py"])
        run.assert_not_called()

    def test_skip_tests_is_diagnostic_not_launch_approval(self):
        with patch.object(launch_gate, "gate_ruff", return_value={"ok": True}), \
             patch.object(launch_gate, "gate_script", return_value={"ok": True}), \
             patch.object(launch_gate, "gate_receipts", return_value={"ok": True}), \
             patch.object(launch_gate, "gate_soak_evidence", return_value={"ok": True}), \
             patch.object(launch_gate, "gate_tests") as tests:
            self.assertEqual(launch_gate.main(["--skip-tests"]), 1)
        tests.assert_not_called()



class ToolMissingIsDistinctFromSourceFailure(unittest.TestCase):
    def test_missing_ruff_is_tool_missing_not_lint_fail(self):
        with patch.object(launch_gate, "_run", return_value=(1, "No module named ruff\n")):
            result = launch_gate.gate_ruff()
        self.assertFalse(result["ok"])
        self.assertEqual(result["tool_missing"], "ruff")

    def test_real_lint_failure_is_not_tool_missing(self):
        with patch.object(launch_gate, "_run", return_value=(1, "src/x.py:1: E501 line too long")):
            result = launch_gate.gate_ruff()
        self.assertFalse(result["ok"])
        self.assertNotIn("tool_missing", result)

    def test_missing_pytest_is_tool_missing_not_test_fail(self):
        with patch.object(launch_gate, "_run", return_value=(1, "No module named pytest")):
            result = launch_gate.gate_tests(False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["tool_missing"], "pytest")

    def test_real_test_failure_is_not_tool_missing(self):
        with patch.object(
            launch_gate, "_run", return_value=(1, "1 failed, 10 passed in 3.00s")
        ):
            result = launch_gate.gate_tests(True)
        self.assertFalse(result["ok"])
        self.assertNotIn("tool_missing", result)

    def test_report_decision_distinguishes_tool_missing_from_no_go(self):
        tool_missing = {"ruff": {"ok": False, "tool_missing": "ruff"}, "t": {"ok": True}}
        report = launch_gate.build_report(tool_missing, launch_gate.GA_BLOCKERS)
        self.assertEqual(report["decision"], "NO_GO_TOOL_MISSING")
        self.assertEqual(report["tool_missing"], ["ruff"])
        # A genuine source failure with tools present stays plain NO_GO.
        src_fail = {"ruff": {"ok": False}, "t": {"ok": True}}
        self.assertEqual(
            launch_gate.build_report(src_fail, launch_gate.GA_BLOCKERS)["decision"], "NO_GO"
        )
        self.assertEqual(
            launch_gate.build_report(src_fail, launch_gate.GA_BLOCKERS)["tool_missing"], []
        )

    def test_tool_missing_exit_code_is_2(self):
        with (
            patch.object(launch_gate, "gate_ruff",
                         return_value={"ok": False, "tool_missing": "ruff"}),
            patch.object(launch_gate, "gate_script", return_value={"ok": True}),
            patch.object(launch_gate, "gate_receipts", return_value={"ok": True}),
            patch.object(launch_gate, "gate_soak_evidence", return_value={"ok": True}),
            patch.object(launch_gate, "gate_tests", return_value={"ok": True}),
        ):
            self.assertEqual(launch_gate.main([]), 2)

    def test_tool_missing_gate_sets_stay_deterministic_across_key_order(self):
        g1 = {"a": {"ok": False, "tool_missing": "ruff"}, "b": {"ok": False, "tool_missing": "pytest"}}
        g2 = {"b": {"ok": False, "tool_missing": "pytest"}, "a": {"ok": False, "tool_missing": "ruff"}}
        r1 = launch_gate.build_report(g1, [])
        r2 = launch_gate.build_report(g2, [])
        self.assertEqual(r1["digest"], r2["digest"])
        self.assertEqual(r1["tool_missing"], ["pytest", "ruff"])


if __name__ == "__main__":
    unittest.main()


class IndependentRuntimeBlockers(unittest.TestCase):
    def test_runtime_blockers_cannot_be_hidden_by_green_focused_suites(self):
        gate = launch_gate.gate_runtime_blockers()
        self.assertFalse(gate["ok"])
        self.assertEqual({row["issue"] for row in gate["blockers"]}, {223, 225})
        report = launch_gate.build_report({"tests": {"ok": True}, "runtime_blockers": gate}, [])
        self.assertEqual(report["decision"], "NO_GO")

    def test_closed_option_c_issue_is_not_a_ga_blocker(self):
        self.assertNotIn(198, {row["issue"] for row in launch_gate.GA_BLOCKERS})
