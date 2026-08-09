"""Non-fabrication and real-git validator tests for Phase C R2C control candidates manifest (Prompt B)."""

import copy
import json
import unittest
from pathlib import Path

from eval.r2c_control_candidates import LOCAL_REPOS, build_r2c_candidates
from eval.r2c_validate import is_repeated_nibble_sha, validate_r2c_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestR2CControlCandidatesValidation(unittest.TestCase):
    def setUp(self):
        manifest_path = REPO_ROOT / "r2c-control-candidates-manifest.json"
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            self.manifest = build_r2c_candidates()

    def test_generated_r2c_manifest_passes_validator(self):
        """Generated R2C manifest must pass validate_r2c_manifest with zero errors."""
        errors = validate_r2c_manifest(self.manifest, LOCAL_REPOS)
        self.assertEqual(errors, [], f"Real R2C manifest failed validation: {errors}")
        self.assertGreaterEqual(len(self.manifest["candidates"]), 80)

    def test_validator_rejects_prefilled_human_adjudication(self):
        """validate_r2c_manifest must reject any manifest with prefilled human adjudication fields."""
        m = copy.deepcopy(self.manifest)
        m["candidates"][0]["human_decision"] = "eligible"
        errors = validate_r2c_manifest(m)
        self.assertTrue(any("prefilled" in e for e in errors), f"Expected prefilled human decision error, got: {errors}")

    def test_validator_rejects_insufficient_candidates_count(self):
        """validate_r2c_manifest must reject manifests with fewer than 80 control candidates."""
        m = copy.deepcopy(self.manifest)
        m["candidates"] = m["candidates"][:50]
        errors = validate_r2c_manifest(m)
        self.assertTrue(any("Insufficient control candidates count" in e for e in errors), f"Expected insufficient count error, got: {errors}")

    def test_validator_rejects_synthetic_repeated_nibble_shas(self):
        """validate_r2c_manifest must detect and reject synthetic/repeated-nibble SHAs."""
        m = copy.deepcopy(self.manifest)
        m["candidates"][0]["real_base_sha"] = "1111111111111111111111111111111111111111"
        errors = validate_r2c_manifest(m)
        self.assertTrue(any("synthetic" in e for e in errors), f"Expected synthetic SHA error, got: {errors}")

        self.assertTrue(is_repeated_nibble_sha("1212121212121212121212121212121212121212"))

    def test_validator_rejects_observation_window_below_90_days(self):
        """validate_r2c_manifest must reject candidates with observation window under 90 days."""
        m = copy.deepcopy(self.manifest)
        m["candidates"][0]["observation_window_days"] = 45
        errors = validate_r2c_manifest(m)
        self.assertTrue(any("observation_window_days" in e for e in errors), f"Expected observation window error, got: {errors}")

    def test_validator_rejects_duplicate_candidate_ids(self):
        """validate_r2c_manifest must reject manifests with duplicate candidate IDs."""
        m = copy.deepcopy(self.manifest)
        m["candidates"][1]["candidate_id"] = m["candidates"][0]["candidate_id"]
        errors = validate_r2c_manifest(m)
        self.assertTrue(any("Duplicate candidate_id" in e for e in errors), f"Expected duplicate candidate ID error, got: {errors}")

    def test_validator_rejects_non_existent_git_commits(self):
        """validate_r2c_manifest must fail when a claimed real_base_sha does not exist in real clone."""
        m = copy.deepcopy(self.manifest)
        m["candidates"][0]["real_base_sha"] = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        test_repo_map = {m["candidates"][0]["repository"]: REPO_ROOT}
        errors = validate_r2c_manifest(m, test_repo_map)
        self.assertTrue(any("does not exist in real clone" in e for e in errors), f"Expected missing commit error, got: {errors}")


if __name__ == "__main__":
    unittest.main()
