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
        assert "SIGNER_UNVERIFIED" in msg

        # With matching expected signer
        pub_hex = signed["signature"]["verifying_key"]
        ok, msg = verify_receipt(signed, key_path=key_file, expected_signer=pub_hex)
        assert ok is True
        assert "SIGNER_TRUSTED" in msg

        # With mismatched expected signer
        ok, msg = verify_receipt(signed, key_path=key_file, expected_signer="00" * 32)
        assert ok is True
        assert "SIGNER_UNTRUSTED" in msg


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


def test_signing_key_path_env_var():
    from unittest import mock

    from jittest.receipt import get_or_create_signing_key

    with tempfile.TemporaryDirectory() as tmpdir:
        custom_key = Path(tmpdir) / "custom_key.pem"
        with mock.patch.dict("os.environ", {"JITTEST_SIGNING_KEY_PATH": str(custom_key)}):
            seed = get_or_create_signing_key()
            assert custom_key.exists()
            assert len(seed) == 32


def test_signing_key_posix_mode_refusal():
    from unittest import mock

    import pytest

    from jittest.receipt import SigningKeyError, get_or_create_signing_key

    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / "posix_key.pem"
        seed = get_or_create_signing_key(key_file)
        assert len(seed) == 32

        # Mock stat mode as 0o644 on posix (group/world readable)
        orig_stat = Path.stat
        mock_stat = mock.Mock()
        mock_stat.st_mode = 0o100644

        def selective_stat(self, *args, **kwargs):
            if getattr(self, "name", None) == key_file.name:
                return mock_stat
            return orig_stat(self, *args, **kwargs)

        with mock.patch("jittest.receipt._is_posix", return_value=True), mock.patch.object(Path, "stat", selective_stat):
            with pytest.raises(SigningKeyError) as ctx:
                get_or_create_signing_key(key_file)
            assert "group- or world-readable" in str(ctx.value)


def test_signing_key_never_passed_to_sandbox_wrap():
    from jittest.receipt import get_or_create_signing_key
    from jittest.sandbox import SandboxPlan
    from jittest.sandbox import wrap as sandbox_wrap

    with tempfile.TemporaryDirectory() as tmpdir:
        key_file = Path(tmpdir) / "secret_key.pem"
        get_or_create_signing_key(key_file)
        workdir = Path(tmpdir) / "workspace"
        workdir.mkdir()
        env = {"PATH": "/usr/bin", "JITTEST_SIGNING_KEY_PATH": str(key_file)}

        docker_plan = SandboxPlan(backend="docker", image="python:3.13-slim")
        argv, wrapped_env = sandbox_wrap(["python", "-c", "print(1)"], workdir, env, docker_plan)

        # 1. Key path must NOT be in argv (not mounted)
        joined_argv = " ".join(argv)
        assert str(key_file) not in joined_argv
        assert ".jittest" not in joined_argv

        # 2. Key path env var must NOT be passed to container
        assert "JITTEST_SIGNING_KEY_PATH" not in wrapped_env
