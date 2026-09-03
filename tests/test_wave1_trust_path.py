"""Regression tests for Wave 1 defects D3, D4, and D6.

- D3: Symlink / out-of-repo test path containment in verify.py
- D4: Signer prefix floor (16 hex minimum) in receipt.py
- D6: Unique evidence artifact filenames for same-stem test files in action.py"""

import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest.action import run_action
from jittest.receipt import sign_evidence, verify_receipt
from jittest.verify import VerifyRefusalError, verify_test


class TestWave1D3PathContainment(unittest.TestCase):
    def test_out_of_repo_path_refuses_without_reading_or_executing(self):
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as outside_dir:
            repo = Path(repo_dir)
            outside_file = Path(outside_dir) / "evil.py"
            outside_file.write_text("def test_evil(): assert True\n", encoding="utf-8")

            with self.assertRaises(VerifyRefusalError) as ctx:
                verify_test(
                    repo_path=repo,
                    base_ref="HEAD",
                    head_ref="HEAD",
                    test_file_path=outside_file,
                )
            self.assertIn("outside repository", str(ctx.exception).lower())

    def test_symlink_pointing_outside_repo_refuses_without_reading(self):
        with tempfile.TemporaryDirectory() as repo_dir, tempfile.TemporaryDirectory() as outside_dir:
            repo = Path(repo_dir)
            outside_file = Path(outside_dir) / "evil.py"
            outside_file.write_text("def test_evil(): assert True\n", encoding="utf-8")
            symlink_path = repo / "test_symlink.py"
            try:
                os.symlink(outside_file, symlink_path)
            except (OSError, NotImplementedError):
                symlink_path.write_text("# symlink placeholder\n", encoding="utf-8")
                with patch.object(Path, "is_relative_to", return_value=False):
                    with self.assertRaises(VerifyRefusalError) as ctx:
                        verify_test(
                            repo_path=repo,
                            base_ref="HEAD",
                            head_ref="HEAD",
                            test_file_path=symlink_path,
                        )
                    self.assertIn("outside repository", str(ctx.exception).lower())
                return

            with self.assertRaises(VerifyRefusalError) as ctx:
                verify_test(
                    repo_path=repo,
                    base_ref="HEAD",
                    head_ref="HEAD",
                    test_file_path=symlink_path,
                )
            self.assertIn("outside repository", str(ctx.exception).lower())

    def test_directory_test_path_refuses_as_regular_file(self):
        with tempfile.TemporaryDirectory() as repo_dir:
            repo = Path(repo_dir)
            test_dir = repo / "test_folder"
            test_dir.mkdir()
            with self.assertRaises(VerifyRefusalError) as ctx:
                verify_test(
                    repo_path=repo,
                    base_ref="HEAD",
                    head_ref="HEAD",
                    test_file_path=test_dir,
                )
            self.assertIn("not a regular file", str(ctx.exception).lower())


class TestWave1D4SignerFloor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "test_key.pem"
        evidence = {
            "schema_version": "1.0",
            "tool": "jittest verify",
            "verdict": "proven_catch",
            "proven_catch": True,
            "wall_clockIs": 1.0,
        }
        self.signed = sign_evidence(evidence, key_path=self.key_file)
        self.key_hex = self.signed["signature"]["verifying_key"]
        self.fingerprint = hashlib.sha256(bytes.fromhex(self.key_hex)).hexdigest()[:16]

    def tearDown(self):
        self.tmp.cleanup()

    def test_short_prefix_rejected_not_trusted(self):
        short_prefix = self.fingerprint[0]
        ok, msg = verify_receipt(self.signed, expected_signer=short_prefix)
        self.assertTrue(ok)
        self.assertIn("SIGNER_UNTRUSTED", msg)

    def test_fifteen_char_prefix_rejected_not_trusted(self):
        prefix_15 = self.fingerprint[:15]
        ok, msg = verify_receipt(self.signed, expected_signer=prefix_15)
        self.assertTrue(ok)
        self.assertIn("SIGNER_UNTRUSTED", msg)

    def test_sixteen_char_fingerprint_trusted(self):
        ok, msg = verify_receipt(self.signed, expected_signer=self.fingerprint)
        self.assertTrue(ok)
        self.assertIn("SIGNER_TRUSTED", msg)

    def test_random_sixteen_char_non_match_untrusted(self):
        wrong_fp = "0123456789abcdef" if self.fingerprint != "0123456789abcdef" else "fedcba9876543210"
        ok, msg = verify_receipt(self.signed, expected_signer=wrong_fp)
        self.assertTrue(ok)
        self.assertIn("SIGNER_UNTRUSTED", msg)

    def test_full_64_hex_key_trusted(self):
        ok, msg = verify_receipt(self.signed, expected_signer=self.key_hex)
        self.assertTrue(ok)
        self.assertIn("SIGNER_TRUSTED", msg)

    def test_allowlist_file_rejects_short_and_accepts_sixteen(self):
        allowlist = Path(self.tmp.name) / "allowlist.txt"
        allowlist.write_text(f"# comment\n{self.fingerprint[0]}\n", encoding="utf-8")
        ok, msg = verify_receipt(self.signed, expected_signer=allowlist)
        self.assertTrue(ok)
        self.assertIn("SIGNER_UNTRUSTED", msg)

        allowlist.write_text(f"# comment\n{self.fingerprint}\n", encoding="utf-8")
        ok, msg = verify_receipt(self.signed, expected_signer=allowlist)
        self.assertTrue(ok)
        self.assertIn("SIGNER_TRUSTED", msg)


class TestWave1D6UniqueEvidenceNames(unittest.TestCase):
    def test_same_stem_different_subdirs_produce_two_distinct_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            (repo / "tests" / "a").mkdir(parents=True)
            (repo / "tests" / "b").mkdir(parents=True)
            (repo / "tests" / "a" / "test_same.py").write_text("def test_a(): assert True\n", encoding="utf-8")
            (repo / "tests" / "b" / "test_same.py").write_text("def test_b(): assert True\n", encoding="utf-8")
            out_dir = repo / "evidence"

            def mock_verify(*args, **kwargs):
                out = kwargs.get("output_path")
                if out:
                    Path(out).write_text("{}", encoding="utf-8")
                return {"verdict": "proven_catch", "disposition": "PROVEN_CATCH", "proven_catch": True, "wall_clock_s": 0.1}, 0

            with (
                patch("jittest.action.get_changed_files", return_value=["tests/a/test_same.py", "tests/b/test_same.py"]),
                patch("jittest.action.verify_test", side_effect=mock_verify),
                patch("jittest.action.upsert_pr_comment", return_value="comment posted"),
            ):
                rc = run_action(repo_path=repo, output_dir=out_dir)

            self.assertEqual(rc, 0)
            artifacts = list(out_dir.glob("evidence-*.json"))
            self.assertEqual(len(artifacts), 2, f"Expected 2 artifacts, found: {artifacts}")
            names = {a.name for a in artifacts}
            rel_a = "tests/a/test_same.py"
            rel_b = "tests/b/test_same.py"
            hash_a = hashlib.sha256(rel_a.encode("utf-8")).hexdigest()[:12]
            hash_b = hashlib.sha256(rel_b.encode("utf-8")).hexdigest()[:12]
            self.assertIn(f"evidence-test_same-{hash_a}.json", names)
            self.assertIn(f"evidence-test_same-{hash_b}.json", names)


if __name__ == "__main__":
    unittest.main()
