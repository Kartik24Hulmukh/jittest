"""Strict receipt validation tests covering Tasks 10-16 (J2)."""

import tempfile
import unittest
from pathlib import Path

from jittest.receipt import (
    ReceiptVerificationResult,
    sign_evidence,
    validate_schema,
    validate_semantics,
    verify_receipt,
)


def _make_valid_21_evidence() -> dict:
    return {
        "schema_version": "2.1",
        "tool": "jittest verify",
        "verdict": "proven_catch",
        "proven_catch": True,
        "disposition": "catching",
        "provenance": {
            "repo_path": "/tmp/test-repo",
            "repo_canonical": "github.com/example/repo",
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "test_file_name": "test_example.py",
            "test_file_sha256": "c" * 64,
            "tool_commit_sha": "d" * 40,
            "rel_path": ".",
        },
        "sandbox": {
            "mode": "required",
            "backend": "docker",
            "image": "python:3.13-slim",
            "confined": True,
        },
        "base_execution": {
            "outcome": "PASS",
            "failure_kind": "none",
            "exit_code": 0,
            "stdout_sha256": "e" * 64,
            "stderr_sha256": "f" * 64,
        },
        "head_execution": {
            "outcome": "FAIL",
            "failure_kind": "assertion",
            "exit_code": 1,
            "stdout_sha256": "0" * 64,
            "stderr_sha256": "1" * 64,
        },
        "rerun_agreement": True,
        "wall_clock_s": 1.23,
    }


class TestReceiptStrictSchema(unittest.TestCase):
    def test_missing_provenance_is_schema_invalid(self):
        ev = _make_valid_21_evidence()
        del ev["provenance"]
        res = validate_schema(ev)
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "INVALID")
        self.assertTrue(any("provenance" in err for err in res.errors))

    def test_unknown_schema_version_is_unsupported(self):
        ev = _make_valid_21_evidence()
        ev["schema_version"] = "99.0"
        res = validate_schema(ev)
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "UNSUPPORTED")
        self.assertTrue(any("unsupported schema_version" in err for err in res.errors))

    def test_wrong_types_are_structured_invalid_not_exception(self):
        ev = _make_valid_21_evidence()
        ev["wall_clock_s"] = "very fast"
        ev["proven_catch"] = "true"
        res = validate_schema(ev)
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "INVALID")
        self.assertTrue(len(res.errors) >= 2)


class TestReceiptSemantics(unittest.TestCase):
    def test_pass_pass_cannot_be_proven_catch(self):
        ev = _make_valid_21_evidence()
        ev["head_execution"]["outcome"] = "PASS"
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(any("proven_catch" in err for err in res.errors))

    def test_collection_failure_cannot_be_behavioral_catch(self):
        ev = _make_valid_21_evidence()
        ev["head_execution"]["outcome"] = "ERROR"
        ev["head_execution"]["failure_kind"] = "collection"
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(any("collection" in err or "proven_catch" in err for err in res.errors))

    def test_rerun_disagreement_forbids_catch(self):
        ev = _make_valid_21_evidence()
        ev["rerun_agreement"] = False
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(any("rerun_agreement" in err for err in res.errors))


class TestProvenanceAndRepoIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "key.pem"

    def tearDown(self):
        self.tmp.cleanup()

    def test_empty_actual_sha_never_matches(self):
        ev = _make_valid_21_evidence()
        ev["provenance"]["base_sha"] = ""
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed, expected_base="a" * 40)
        self.assertFalse(res.valid)
        self.assertIn(res.provenance_status, ("MISMATCH", "UNRESOLVABLE"))

    def test_abbreviated_expected_requires_resolution(self):
        ev = _make_valid_21_evidence()
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed, expected_base="aaaa")
        self.assertFalse(res.valid)
        self.assertEqual(res.provenance_status, "UNRESOLVABLE")

    def test_expected_repo_substring_no_longer_matches(self):
        ev = _make_valid_21_evidence()
        ev["provenance"]["repo_canonical"] = "github.com/foo/bar-baz"
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed, expected_repo="github.com/foo/bar")
        self.assertFalse(res.valid)
        self.assertEqual(res.provenance_status, "MISMATCH")


class TestNoRaiseContractAndLegacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "key.pem"

    def tearDown(self):
        self.tmp.cleanup()

    def test_non_dict_input_returns_structured_result(self):
        bad_inputs = [None, [1, 2, 3], 12345, "not json and no file"]
        for bad in bad_inputs:
            res = verify_receipt(bad)
            self.assertIsInstance(res, ReceiptVerificationResult)
            self.assertFalse(res.valid)
            self.assertFalse(res.signature_valid)

    def test_legacy_v20_receipt_is_labelled_not_rejected(self):
        ev = {
            "schema_version": "2.0",
            "tool": "jittest verify",
            "verdict": "proven_catch",
            "proven_catch": True,
            "wall_clock_s": 1.0,
            "provenance": {
                "base_sha": "a" * 40,
                "head_sha": "b" * 40,
                "test_file_name": "test_foo.py",
                "test_file_sha256": "c" * 64,
            },
        }
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed)
        self.assertTrue(res.signature_valid)
        self.assertEqual(res.schema_status, "VALID_LEGACY")
        self.assertEqual(res.execution_trust, "UNKNOWN")
        self.assertTrue(res.valid)


class TestEdgeCaseHardening(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.key_file = Path(self.tmp.name) / "key.pem"

    def tearDown(self):
        self.tmp.cleanup()

    def test_refusal_forbids_catch_verdict(self):
        ev = _make_valid_21_evidence()
        ev["refusal"] = {
            "code": "pre_isolation_execution",
            "message": "refused",
            "phase": "plan",
            "details": "",
        }
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(
            any("presence of refusal requires verdict 'inconclusive'" in err for err in res.errors)
        )

    def test_empty_failure_kind_cannot_be_proven_catch(self):
        ev = _make_valid_21_evidence()
        ev["head_execution"]["failure_kind"] = ""
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(any("assertion" in err for err in res.errors))

    def test_collection_catch_requires_collection_failure_kind(self):
        ev = _make_valid_21_evidence()
        ev["verdict"] = "collection_catch"
        ev["proven_catch"] = False
        ev["head_execution"]["outcome"] = "ERROR"
        ev["head_execution"]["failure_kind"] = "timeout"
        res = validate_semantics(ev)
        self.assertFalse(res.valid)
        self.assertTrue(any("collection" in err or "import" in err for err in res.errors))

    def test_wall_clock_boolean_is_schema_invalid(self):
        ev = _make_valid_21_evidence()
        ev["wall_clock_s"] = True
        res = validate_schema(ev)
        self.assertFalse(res.valid)
        self.assertEqual(res.status, "INVALID")

    def test_empty_expected_base_fails(self):
        ev = _make_valid_21_evidence()
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed, expected_base="")
        self.assertFalse(res.valid)
        self.assertEqual(res.provenance_status, "MISMATCH")

    def test_sandbox_mode_off_is_unconfined(self):
        ev = _make_valid_21_evidence()
        ev["sandbox"] = {"mode": "off", "backend": "docker", "image": "python:3.12-slim"}
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed)
        self.assertEqual(res.execution_trust, "UNCONFINED")

    def test_crypto_backend_not_shadowed_by_sandbox_backend(self):
        ev = _make_valid_21_evidence()
        ev["sandbox"]["backend"] = "docker"
        signed = sign_evidence(ev, key_path=self.key_file)
        res = verify_receipt(signed, backend="vendored")
        self.assertTrue(res.signature_valid)
