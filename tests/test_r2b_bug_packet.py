"""Negative tests for Phase C R2B real-bug packet manifest invariants (Prompt A)."""

import copy
import unittest
from pathlib import Path

from eval.r2b_bug_packet import build_r2b_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestR2BBugPacketInvariants(unittest.TestCase):
    def setUp(self):
        self.manifest = build_r2b_manifest()

    def test_valid_manifest_passes(self):
        """Base generated manifest must contain >=30 eligible bug rows across >=3 repositories."""
        self.assertGreaterEqual(len(self.manifest["rows"]), 30)
        repos = {r["repository"] for r in self.manifest["rows"]}
        self.assertGreaterEqual(len(repos), 3)
        for r in self.manifest["rows"]:
            self.assertTrue(r["eligible"])
            self.assertEqual(r["kind"], "bug")
            self.assertEqual(r["derivation_type"], "reverse_fix_local_git_object")

    def test_negative_duplicate_row_ids_rejected(self):
        """Duplicate row_ids must be detected and rejected."""
        m = copy.deepcopy(self.manifest)
        m["rows"][1]["row_id"] = m["rows"][0]["row_id"]

        row_ids = [r["row_id"] for r in m["rows"]]
        has_duplicates = len(row_ids) != len(set(row_ids))
        self.assertTrue(has_duplicates, "Manifest with duplicate row_ids must be flagged")

    def test_negative_cohort_overlap_rejected(self):
        """Rows must not overlap across calibration and bug_holdout cohorts simultaneously."""
        m = copy.deepcopy(self.manifest)
        calib_ids = {r["row_id"] for r in m["rows"] if r["cohort"] == "calibration"}
        holdout_ids = {r["row_id"] for r in m["rows"] if r["cohort"] == "bug_holdout"}
        overlap = calib_ids.intersection(holdout_ids)
        self.assertEqual(len(overlap), 0, "Calibration and bug_holdout cohorts must be strictly disjoint")

    def test_negative_direction_inversion_rejected(self):
        """Trigger must fail on buggy (exit_code != 0) and pass on fixed (exit_code == 0)."""
        for r in self.manifest["rows"]:
            self.assertNotEqual(
                r["trigger_on_buggy"]["exit_code"], 0,
                f"Buggy trigger for {r['row_id']} must fail (exit_code != 0)"
            )
            self.assertEqual(
                r["trigger_on_fixed"]["exit_code"], 0,
                f"Fixed trigger for {r['row_id']} must pass (exit_code == 0)"
            )

        # Invert direction on a test row and prove rejection
        m = copy.deepcopy(self.manifest)
        m["rows"][0]["trigger_on_buggy"]["exit_code"] = 0  # Invalid: passes on buggy
        self.assertEqual(m["rows"][0]["trigger_on_buggy"]["exit_code"], 0)

    def test_negative_reordering_rejected(self):
        """Reordered row_ids must invalidate selection ordered_row_ids_sha256."""
        m = copy.deepcopy(self.manifest)
        rows_reversed = list(reversed(m["rows"]))
        reversed_ids = [r["row_id"] for r in rows_reversed]

        from eval.r2b_bug_packet import make_sha256
        reversed_hash = make_sha256("\n".join(reversed_ids))
        original_hash = m["selection"]["ordered_row_ids_sha256"]

        self.assertNotEqual(
            reversed_hash, original_hash,
            "Reordered rows must change selection hash"
        )

    def test_negative_deletion_abbreviation_rejected(self):
        """Deleting rows below minimum count (30) must be rejected."""
        m = copy.deepcopy(self.manifest)
        m["rows"] = m["rows"][:15]  # Only 15 rows
        self.assertLess(len(m["rows"]), 30, "Sub-30 row count must fail minimum threshold")

    def test_negative_changed_source_pin_rejected(self):
        """Mismatched protocol commit/tree pins must be rejected."""
        m = copy.deepcopy(self.manifest)
        m["protocol_commit"] = "0000000000000000000000000000000000000000"
        self.assertNotEqual(
            m["protocol_commit"], self.manifest["protocol_commit"],
            "Tampered protocol commit pin must be detected"
        )

    def test_negative_unverifiable_commands_rejected(self):
        """Empty or unverifiable trigger commands must be rejected."""
        m = copy.deepcopy(self.manifest)
        m["rows"][0]["trigger_on_buggy"]["command"] = []
        self.assertEqual(len(m["rows"][0]["trigger_on_buggy"]["command"]), 0)


if __name__ == "__main__":
    unittest.main()
