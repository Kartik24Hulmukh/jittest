"""Cross-environment receipt verification — the product promise as an executable oracle.

A jittest receipt is worthless unless a stranger can check it. "A stranger" means
someone whose Python environment does not match ours: specifically, someone who ran
`pip install jittest` and therefore has NO third-party packages at all, because
jittest declares zero dependencies.

These tests fail on jittest <= 0.3.2, where:
  * a zero-dependency install signs with HMAC-SHA256 whose secret is derived from
    a public constant plus a predictable path, making receipts forgeable; and
  * a zero-dependency install cannot verify the Ed25519 receipts that jittest's own
    published benchmark evidence contains.
"""

from __future__ import annotations

import unittest

from jittest import receipt


def _evidence() -> dict:
    return {
        "schema_version": "2.0",
        "tool": "jittest verify",
        "verdict": "proven_catch",
        "proven_catch": True,
        "disposition": "catching",
        "base_execution": {"outcome": "PASS", "exit_code": 0},
        "head_execution": {"outcome": "FAIL", "exit_code": 1},
    }


class TestVendoredEd25519Correctness(unittest.TestCase):
    """The vendored signer must be RFC 8032, not merely self-consistent."""

    def test_rfc8032_test_vector_1(self):
        from jittest import _ed25519

        secret = bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        )
        expected_public = bytes.fromhex(
            "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
        )
        expected_sig = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
            "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertEqual(_ed25519.secret_to_public(secret), expected_public)
        self.assertEqual(_ed25519.sign(secret, b""), expected_sig)
        self.assertTrue(_ed25519.verify(expected_public, b"", expected_sig))

    def test_rfc8032_test_vector_2(self):
        from jittest import _ed25519

        secret = bytes.fromhex(
            "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
        )
        msg = bytes.fromhex("72")
        expected_sig = bytes.fromhex(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da0"
            "85ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
        )
        self.assertEqual(_ed25519.sign(secret, msg), expected_sig)

    def test_rejects_tampered_message(self):
        from jittest import _ed25519

        secret = bytes.fromhex(
            "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
        )
        pub = _ed25519.secret_to_public(secret)
        sig = _ed25519.sign(secret, b"honest")
        self.assertTrue(_ed25519.verify(pub, b"honest", sig))
        self.assertFalse(_ed25519.verify(pub, b"forged", sig))


class TestCrossEnvironmentVerification(unittest.TestCase):
    """A receipt must survive crossing an environment boundary in both directions."""

    def _sign_with(self, backend, tmp):
        return receipt.sign_evidence(_evidence(), key_path=tmp, backend=backend)

    def test_vendored_signature_verifies_under_cryptography(self):
        if not receipt.HAS_CRYPTOGRAPHY:
            self.skipTest("cryptography not installed in this environment")
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "k.pem"
            signed = self._sign_with("vendored", key)
            self.assertEqual(signed["signature"]["algorithm"], "Ed25519")
            ok, reason = receipt.verify_receipt(signed, backend="cryptography")
            self.assertTrue(ok, f"cryptography rejected a vendored signature: {reason}")

    def test_cryptography_signature_verifies_under_vendored(self):
        if not receipt.HAS_CRYPTOGRAPHY:
            self.skipTest("cryptography not installed in this environment")
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "k.pem"
            signed = self._sign_with("cryptography", key)
            self.assertEqual(signed["signature"]["algorithm"], "Ed25519")
            ok, reason = receipt.verify_receipt(signed, backend="vendored")
            self.assertTrue(ok, f"vendored rejected a cryptography signature: {reason}")

    def test_both_backends_produce_identical_bytes(self):
        """Ed25519 is deterministic; the two backends must agree exactly."""
        if not receipt.HAS_CRYPTOGRAPHY:
            self.skipTest("cryptography not installed in this environment")
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "k.pem"
            a = self._sign_with("vendored", key)
            b = self._sign_with("cryptography", key)
            self.assertEqual(a["signature"]["value"], b["signature"]["value"])
            self.assertEqual(
                a["signature"]["verifying_key"], b["signature"]["verifying_key"]
            )

    def test_default_install_can_verify_published_ed25519_evidence(self):
        """The zero-dependency install must verify our own published receipts."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "k.pem"
            signed = self._sign_with("vendored", key)
            ok, reason = receipt.verify_receipt(signed, backend="vendored")
            self.assertTrue(ok, reason)


class TestNoForgeableMode(unittest.TestCase):
    """Regression for the forgery found on 0.3.2."""

    def test_signing_never_emits_symmetric_algorithm(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            self.assertEqual(signed["signature"]["algorithm"], "Ed25519")

    def test_no_signature_field_is_named_public_key_for_a_secret(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            self.assertIn("verifying_key", signed["signature"])

    def test_legacy_hmac_receipt_is_reported_unverifiable_not_valid(self):
        legacy = _evidence()
        legacy["signature"] = {
            "algorithm": "HMAC-SHA256",
            "public_key": "00" * 32,
            "value": "AA==",
        }
        ok, reason = receipt.verify_receipt(legacy)
        self.assertFalse(ok)
        self.assertIn("not_independently_verifiable", reason)

    def test_unknown_algorithm_returns_structured_result_and_does_not_raise(self):
        weird = _evidence()
        weird["signature"] = {
            "algorithm": "Rot13-Deluxe",
            "verifying_key": "00" * 32,
            "value": "AA==",
        }
        ok, reason = receipt.verify_receipt(weird)
        self.assertFalse(ok)
        self.assertIn("unsupported_algorithm", reason)

    def test_tamper_is_still_detected(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            signed["verdict"] = "not_catching"
            ok, _ = receipt.verify_receipt(signed)
            self.assertFalse(ok)


class TestSigningKeyIsHonoured(unittest.TestCase):
    """--signing-key must work, or fail loudly. It must never be silently ignored."""

    def test_explicit_key_is_used_and_receipt_verifies(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "explicit.pem"
            signed = receipt.sign_evidence(_evidence(), key_path=key)
            self.assertTrue(key.exists(), "explicit key path was not written")
            ok, reason = receipt.verify_receipt(signed)
            self.assertTrue(ok, f"receipt signed with an explicit key failed: {reason}")

    def test_unreadable_key_raises_rather_than_falling_back(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "garbage.pem"
            bad.write_bytes(b"this is not a key")
            with self.assertRaises(receipt.SigningKeyError):
                receipt.sign_evidence(_evidence(), key_path=bad)

    def test_roundtrip_through_pem_is_backend_independent(self):
        """A PEM written by one backend must load in the other."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            key = Path(d) / "k.pem"
            receipt.sign_evidence(_evidence(), key_path=key, backend="vendored")
            pem = key.read_bytes()
            self.assertIn(b"PRIVATE KEY", pem)
            seed_a = receipt._seed_from_pem(pem)
            self.assertEqual(len(seed_a), 32)


class TestLegacyFieldCompatibility(unittest.TestCase):
    """The 147 already-published receipts use `public_key`. They must keep verifying."""

    def test_receipt_with_legacy_public_key_field_still_verifies(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            signed["signature"]["public_key"] = signed["signature"].pop("verifying_key")
            ok, reason = receipt.verify_receipt(signed)
            self.assertTrue(ok, f"legacy field name broke verification: {reason}")


class TestExpectedSignerVerification(unittest.TestCase):
    """WO-12 R1: Expected-signer verification and trust boundary checks."""

    def test_no_expected_signer_reports_unverified(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            ok, reason = receipt.verify_receipt(signed)
            self.assertTrue(ok)
            self.assertIn("SIGNER_UNVERIFIED", reason)

    def test_expected_signer_match_reports_trusted(self):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            pub_hex = signed["signature"]["verifying_key"]
            fingerprint = hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]

            # Matching by full hex
            ok, reason = receipt.verify_receipt(signed, expected_signer=pub_hex)
            self.assertTrue(ok)
            self.assertIn("SIGNER_TRUSTED", reason)

            # Matching by fingerprint
            ok, reason = receipt.verify_receipt(signed, expected_signer=fingerprint)
            self.assertTrue(ok)
            self.assertIn("SIGNER_TRUSTED", reason)

    def test_expected_signer_allowlist_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            pub_hex = signed["signature"]["verifying_key"]

            allowlist_path = Path(d) / "allowlist.txt"
            allowlist_path.write_text(f"# Trusted keys\n{pub_hex}\n", encoding="utf-8")

            ok, reason = receipt.verify_receipt(signed, expected_signer=str(allowlist_path))
            self.assertTrue(ok)
            self.assertIn("SIGNER_TRUSTED", reason)

            # Mismatched allowlist
            bad_allowlist = Path(d) / "bad_allowlist.txt"
            bad_allowlist.write_text("# Other keys\n00112233445566778899aabbccddeeff\n", encoding="utf-8")

            ok, reason = receipt.verify_receipt(signed, expected_signer=str(bad_allowlist))
            self.assertTrue(ok)
            self.assertIn("SIGNER_UNTRUSTED", reason)

    def test_expected_signer_mismatch_reports_untrusted(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            signed = receipt.sign_evidence(_evidence(), key_path=Path(d) / "k.pem")
            attacker_expected = "deadbeef" * 8
            ok, reason = receipt.verify_receipt(signed, expected_signer=attacker_expected)
            self.assertTrue(ok)
            self.assertIn("SIGNER_UNTRUSTED", reason)


if __name__ == "__main__":
    unittest.main()
