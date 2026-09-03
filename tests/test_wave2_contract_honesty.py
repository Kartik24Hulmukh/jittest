"""Regression tests for Wave 2 defects D7 and D5.

- D7: Schema/source disagreement (six verdicts, verifying_key, proven_catch invariant).
- D5: verify_receipt validates semantics and provenance (signature valid != schema valid != signer trusted != provenance matched).
"""

import tempfile
import unittest
from pathlib import Path

from jittest.receipt import sign_evidence, verify_receipt


class TestWave2D7SchemaAndVerdictInvariants(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "test_key.pem"

    def tearDown(self):
        self.tmp.cleanup()

    def _make_receipt(self, verdict: str, proven_catch: bool, key_field: str = "verifying_key"):
        evidence = {
            "schema_version": "2.0",
            "tool": "jittest verify",
            "verdict": verdict,
            "proven_catch": proven_catch,
            "wall_clock_s": 1.0,
            "provenance": {
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "test_file_name": "test_foo.py",
                "test_file_sha256": "c" * 64,
            },
        }
        signed = sign_evidence(evidence, key_path=self.key_file)
        if key_field == "public_key":
            vk = signed["signature"].pop("verifying_key", None)
            if vk:
                signed["signature"]["public_key"] = vk
        return signed

    def test_all_six_verdicts_pass_schema_validation(self):
        verdict_expectations = [
            ("proven_catch", True),
            ("reproduction_catch", True),
            ("collection_catch", False),
            ("refuted", False),
            ("non_discriminating", False),
            ("inconclusive", False),
        ]
        for verdict, pc in verdict_expectations:
            with self.subTest(verdict=verdict, proven_catch=pc):
                receipt = self._make_receipt(verdict, pc)
                res = verify_receipt(receipt)
                ok, msg = res[0], res[1]
                self.assertTrue(ok, f"Failed on verdict {verdict}: {msg}")
                self.assertIn("SCHEMA_VALID", msg)

    def test_schema_rejects_unknown_verdict(self):
        receipt = self._make_receipt("unknown_verdict_class", False)
        res = verify_receipt(receipt)
        ok, msg = res[0], res[1]
        self.assertFalse(ok)
        self.assertIn("SCHEMA_INVALID", msg)
        self.assertIn("unknown_verdict", msg)

    def test_proven_catch_invariant_violations_rejected(self):
        # Invariant: proven_catch is True iff verdict in (proven_catch, reproduction_catch)
        violations = [
            ("proven_catch", False),
            ("reproduction_catch", False),
            ("refuted", True),
            ("collection_catch", True),
            ("non_discriminating", True),
            ("inconclusive", True),
        ]
        for verdict, pc in violations:
            with self.subTest(verdict=verdict, proven_catch=pc):
                receipt = self._make_receipt(verdict, pc)
                res = verify_receipt(receipt)
                ok, msg = res[0], res[1]
                self.assertFalse(ok)
                self.assertIn("SCHEMA_INVALID", msg)
                self.assertIn("proven_catch_invariant_violation", msg)

    def test_schema_accepts_verifying_key_and_legacy_public_key(self):
        for kfield in ("verifying_key", "public_key"):
            with self.subTest(key_field=kfield):
                receipt = self._make_receipt("proven_catch", True, key_field=kfield)
                res = verify_receipt(receipt)
                self.assertTrue(res[0])
                self.assertIn("SIGNATURE_VALID", res[1])


class TestWave2D5ReceiptSemanticsAndProvenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "test_key.pem"
        self.base_sha = "1111111111111111111111111111111111111111"
        self.head_sha = "2222222222222222222222222222222222222222"
        self.test_sha = "3333333333333333333333333333333333333333333333333333333333333333"
        self.evidence = {
            "schema_version": "2.0",
            "tool": "jittest verify",
            "verdict": "proven_catch",
            "proven_catch": True,
            "wall_clock_s": 0.5,
            "provenance": {
                "repo_path": "/path/to/myrepo",
                "base_sha": self.base_sha,
                "head_sha": self.head_sha,
                "test_file_name": "test_foo.py",
                "test_file_sha256": self.test_sha,
            },
        }
        self.signed = sign_evidence(self.evidence, key_path=self.key_file)
        self.pub_hex = self.signed["signature"]["verifying_key"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_distinct_verification_facets(self):
        res = verify_receipt(self.signed, expected_signer=self.pub_hex)
        self.assertTrue(res[0])
        self.assertTrue(hasattr(res, "signature_valid"))
        self.assertTrue(hasattr(res, "signer_status"))
        self.assertTrue(hasattr(res, "schema_valid"))
        self.assertTrue(res.signature_valid)
        self.assertEqual(res.signer_status, "TRUSTED")
        self.assertTrue(res.schema_valid)

    def test_provenance_base_matching_and_mismatch(self):
        res_ok = verify_receipt(self.signed, expected_base=self.base_sha[:8])
        self.assertTrue(res_ok[0])
        self.assertIn("PROVENANCE_MATCHED", res_ok[1])

        res_fail = verify_receipt(self.signed, expected_base="99999999")
        self.assertFalse(res_fail[0])
        self.assertIn("PROVENANCE_MISMATCH", res_fail[1])

    def test_provenance_head_matching_and_mismatch(self):
        res_ok = verify_receipt(self.signed, expected_head=self.head_sha[:8])
        self.assertTrue(res_ok[0])
        self.assertIn("PROVENANCE_MATCHED", res_ok[1])

        res_fail = verify_receipt(self.signed, expected_head="99999999")
        self.assertFalse(res_fail[0])
        self.assertIn("PROVENANCE_MISMATCH", res_fail[1])

    def test_provenance_test_sha256_matching_and_mismatch(self):
        res_ok = verify_receipt(self.signed, expected_test_sha256=self.test_sha)
        self.assertTrue(res_ok[0])
        self.assertIn("PROVENANCE_MATCHED", res_ok[1])

        res_fail = verify_receipt(self.signed, expected_test_sha256="00" * 32)
        self.assertFalse(res_fail[0])
        self.assertIn("PROVENANCE_MISMATCH", res_fail[1])


if __name__ == "__main__":
    unittest.main()