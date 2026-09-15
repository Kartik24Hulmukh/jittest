"""Regression tests for scripts/launch_gate.py (launch go/no-go aggregator)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

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
        rel = "docs/evidence/quadrants/non_discriminating_evidence.json"
        refused = {"signature_valid": True, "valid": False, "semantic_valid": False}
        self.assertTrue(launch_gate.classify_receipt(rel, 5, refused)["ok"])
        # If someone silently makes it pass, the gate must notice.
        accepted = {"signature_valid": True, "valid": True, "semantic_valid": True}
        self.assertFalse(launch_gate.classify_receipt(rel, 0, accepted)["ok"])
        # A tampered signature is never acceptable, refused or not.
        self.assertFalse(
            launch_gate.classify_receipt(rel, 5, dict(refused, signature_valid=False))["ok"]
        )


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


if __name__ == "__main__":
    unittest.main()
