"""Non-fabrication and real-git validator tests for Phase C R2B real-bug packet manifest (Prompt A)."""

import copy
import json
import unittest
from pathlib import Path

from eval.r2b_bug_packet import LOCAL_REPOS, build_r2b_manifest
from eval.r2b_validate import is_repeated_nibble_sha, validate_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestR2BRealBugPacketValidation(unittest.TestCase):
    def setUp(self):
        manifest_path = REPO_ROOT / "r2b-bug-packet-manifest.json"
        if manifest_path.exists():
            self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        else:
            self.manifest = build_r2b_manifest()

    def test_generated_real_manifest_passes_validator(self):
        """Generated real manifest must pass validate_manifest with zero errors."""
        errors = validate_manifest(self.manifest, LOCAL_REPOS)
        self.assertEqual(errors, [], f"Real manifest failed validation: {errors}")

    def test_validator_rejects_synthetic_repeated_nibble_shas(self):
        """validate_manifest must detect and reject synthetic/repeated-nibble SHAs."""
        m = copy.deepcopy(self.manifest)
        m["rows"][0]["real_buggy_sha"] = "1111111111111111111111111111111111111111"
        errors = validate_manifest(m)
        self.assertTrue(any("synthetic SHA" in e for e in errors), f"Expected synthetic SHA error, got: {errors}")

        self.assertTrue(is_repeated_nibble_sha("1212121212121212121212121212121212121212"))
        self.assertTrue(is_repeated_nibble_sha("0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a"))

    def test_validator_rejects_placeholder_source_revisions(self):
        """validate_manifest must reject placeholder source snapshot revisions."""
        m = copy.deepcopy(self.manifest)
        m["source_snapshots"][0]["revision"] = "1212121212121212121212121212121212121212"
        errors = validate_manifest(m)
        self.assertTrue(any("placeholder revision" in e for e in errors), f"Expected placeholder revision error, got: {errors}")

    def test_validator_rejects_duplicate_started_at_timestamps(self):
        """validate_manifest must reject manifests where rows share identical started_at timestamps."""
        m = copy.deepcopy(self.manifest)
        m["rows"][1]["trigger_on_buggy"]["started_at"] = m["rows"][0]["trigger_on_buggy"]["started_at"]
        errors = validate_manifest(m)
        self.assertTrue(any("duplicate started_at" in e for e in errors), f"Expected duplicate timestamp error, got: {errors}")

    def test_validator_rejects_duplicate_stdout_sha256(self):
        """validate_manifest must reject manifests where rows share identical stdout_sha256 digests."""
        m = copy.deepcopy(self.manifest)
        m["rows"][1]["trigger_on_buggy"]["stdout_sha256"] = m["rows"][0]["trigger_on_buggy"]["stdout_sha256"]
        errors = validate_manifest(m)
        self.assertTrue(any("duplicate stdout_sha256" in e for e in errors), f"Expected duplicate stdout error, got: {errors}")

    def test_validator_rejects_exact_mib_byte_counts(self):
        """validate_manifest must reject exact MiB byte counts."""
        m = copy.deepcopy(self.manifest)
        m["source_snapshots"][0]["byte_count"] = 1048576  # Exactly 1 MiB
        errors = validate_manifest(m)
        self.assertTrue(any("fabricated exact MiB" in e for e in errors), f"Expected exact MiB error, got: {errors}")

    def test_validator_rejects_non_existent_git_commits(self):
        """validate_manifest must fail when a claimed real_buggy_sha does not exist in local clone."""
        m = copy.deepcopy(self.manifest)
        m["rows"][0]["real_buggy_sha"] = "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0"
        errors = validate_manifest(m, LOCAL_REPOS)
        self.assertTrue(any("does not exist in real clone" in e for e in errors), f"Expected missing commit error, got: {errors}")


if __name__ == "__main__":
    unittest.main()
