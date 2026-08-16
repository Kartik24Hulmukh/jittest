"""Tests for Ed25519 signed evidence receipts and offline verification.

Updated when symmetric signing was removed. The previous version asserted that a
zero-dependency install CANNOT verify an Ed25519 receipt ("UNVERIFIABLE"), which
encoded the 0.3.2 defect as expected behaviour. Every install can now verify.
"""

import tempfile
from pathlib import Path

from jittest.receipt import sign_evidence, verify_receipt


def test_sign_and_verify_receipt():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / "test_key.pem"
        evidence = {
            "schema_version": "1.0",
            "tool": "jittest verify",
            "verdict": "proven_catch",
            "proven_catch": True,
            "wall_clock_s": 1.234,
        }

        signed = sign_evidence(evidence, key_path=key_file)
        assert "signature" in signed
        assert signed["signature"]["algorithm"] == "Ed25519"
        assert "verifying_key" in signed["signature"]

        # Verifiable in every install, with or without `cryptography`.
        ok, msg = verify_receipt(signed, key_path=key_file)
        assert ok is True
        assert msg == "signature_valid"


def test_tampered_receipt_fails():
    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / "test_key.pem"
        evidence = {
            "schema_version": "1.0",
            "tool": "jittest verify",
            "verdict": "proven_catch",
            "proven_catch": True,
        }

        signed = sign_evidence(evidence, key_path=key_file)

        # Tamper payload
        signed["verdict"] = "non_discriminating"

        ok, msg = verify_receipt(signed, key_path=key_file)
        assert ok is False
