"""Tests for Ed25519 signed evidence receipts and offline verification."""

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
        assert signed["signature"]["algorithm"] in ("Ed25519", "HMAC-SHA256")

        # Verify valid receipt
        ok, msg = verify_receipt(signed)
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

        ok, msg = verify_receipt(signed)
        assert ok is False
        assert "signature_verification_failed" in msg
