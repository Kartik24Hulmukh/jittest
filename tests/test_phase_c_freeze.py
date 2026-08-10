"""Unit tests for Phase C immutable measurement freeze artifacts."""

import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPhaseCFreezeArtifacts(unittest.TestCase):
    def setUp(self):
        self.freeze_config_path = REPO_ROOT / "phase-c-freeze-config.json"
        self.benchmark_manifest_path = REPO_ROOT / "phase-c-benchmark-manifest.json"
        self.freeze_receipt_path = REPO_ROOT / "phase-c-freeze-receipt.json"

        self.assertTrue(self.freeze_config_path.exists(), "phase-c-freeze-config.json must exist")
        self.assertTrue(self.benchmark_manifest_path.exists(), "phase-c-benchmark-manifest.json must exist")
        self.assertTrue(self.freeze_receipt_path.exists(), "phase-c-freeze-receipt.json must exist")

        self.freeze_config = json.loads(self.freeze_config_path.read_text(encoding="utf-8"))
        self.benchmark_manifest = json.loads(self.benchmark_manifest_path.read_text(encoding="utf-8"))
        self.freeze_receipt = json.loads(self.freeze_receipt_path.read_text(encoding="utf-8"))

    def test_freeze_config_structure_and_counts(self):
        """Verify phase-c-freeze-config.json structure and cohort counts."""
        self.assertEqual(self.freeze_config["model"], "mistral/codestral-2508")
        self.assertEqual(self.freeze_config["endpoint"], "https://api.mistral.ai/v1/chat/completions")
        self.assertEqual(self.freeze_config["prompt_version"], "v1.4")

        counts = self.freeze_config["counts"]
        self.assertEqual(counts["calibration"], 7)
        self.assertEqual(counts["bug_holdout"], 16)
        self.assertEqual(counts["control_holdout"], 60)
        self.assertEqual(counts["total"], 83)

        cohorts = self.freeze_config["cohorts"]
        self.assertEqual(len(cohorts["calibration"]), 7)
        self.assertEqual(len(cohorts["bug_holdout"]), 16)
        self.assertEqual(len(cohorts["control_holdout"]), 60)

    def test_benchmark_manifest_rows(self):
        """Verify phase-c-benchmark-manifest.json row breakdown."""
        rows = self.benchmark_manifest["rows"]
        self.assertEqual(len(rows), 83)

        calib_rows = [r for r in rows if r.get("cohort") == "calibration"]
        bug_holdouts = [r for r in rows if r.get("cohort") == "bug_holdout"]
        ctl_holdouts = [r for r in rows if r.get("cohort") == "control_holdout"]

        self.assertEqual(len(calib_rows), 7)
        self.assertEqual(len(bug_holdouts), 16)
        self.assertEqual(len(ctl_holdouts), 60)

    def test_freeze_receipt(self):
        """Verify phase-c-freeze-receipt.json configuration and validation summary."""
        counts = self.freeze_receipt["counts"]
        self.assertEqual(counts["calibration"], 7)
        self.assertEqual(counts["bug_holdout"], 16)
        self.assertEqual(counts["control_holdout"], 60)
        self.assertEqual(counts["total_eval_rows"], 83)

        summary = self.freeze_receipt["validation_summary"]
        self.assertIn("PASS", summary["r2b_validate"])
        self.assertIn("PASS", summary["r2c_validate"])
        self.assertIn("PASS", summary["benchmark_manifest_rows"])


if __name__ == "__main__":
    unittest.main()
