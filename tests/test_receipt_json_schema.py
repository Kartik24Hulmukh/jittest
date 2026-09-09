"""schemas/receipt-2.1.schema.json must mirror receipt.py and accept real receipts."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from jittest import receipt as R

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "receipt-2.1.schema.json"
NEG = ROOT / "tests" / "fixtures" / "receipts" / "negative"

try:
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - optional dev dependency
    jsonschema = None


def _minimal_receipt() -> dict:
    ex = {"outcome": "PASS", "failure_kind": "none", "exit_code": 0,
          "stdout_sha256": "0" * 64, "stderr_sha256": "0" * 64, "environment": {}}
    return {
        "schema_version": "2.1", "tool": "jittest verify", "verdict": "proven_catch",
        "proven_catch": True, "disposition": "catching", "refusal": None,
        "provenance": {"repo_path": ".", "repo_canonical": "github.com/org/repo",
                       "base_sha": "a" * 40, "head_sha": "b" * 40, "test_file_name": "test_x.py",
                       "test_file_sha256": "c" * 64, "tool_commit_sha": "d" * 40, "rel_path": "."},
        "sandbox": {"mode": "required", "backend": "docker", "image": "python:3.13-slim",
                    "isolated": True, "network_denied": True, "notes": []},
        "base_execution": ex,
        "head_execution": {**ex, "outcome": "FAIL", "exit_code": 1, "failure_kind": "assertion"},
        "rerun_agreement": True, "wall_clock_s": 1.5, "provider_cost_usd": 0.0,
    }


class SchemaFileAgreesWithCode(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_required_top_level_matches_receipt_py(self):
        self.assertEqual(set(self.schema["required"]), set(R.REQUIRED_TOP_LEVEL))

    def test_required_provenance_matches_receipt_py(self):
        self.assertEqual(set(self.schema["properties"]["provenance"]["required"]), set(R.REQUIRED_PROVENANCE))

    def test_verdict_enum_matches_receipt_py(self):
        self.assertEqual(set(self.schema["properties"]["verdict"]["enum"]), set(R.VALID_VERDICTS))

    def test_schema_version_is_2_1(self):
        self.assertEqual(self.schema["properties"]["schema_version"]["const"], "2.1")
        self.assertIn("2.1", R.SUPPORTED_SCHEMA_VERSIONS)


class SchemaValidatesRealReceipts(unittest.TestCase):
    def setUp(self):
        if jsonschema is None:
            self.skipTest("jsonschema not installed")
        self.validator = jsonschema.Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    def test_signed_minimal_receipt_validates(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            signed = R.sign_evidence(_minimal_receipt(), key_path=Path(td) / "k")
        errs = sorted(self.validator.iter_errors(signed), key=str)
        self.assertEqual(errs, [], [e.message for e in errs])
        self.assertTrue(R.validate_schema(signed).valid)

    def test_proven_catch_invariant_enforced(self):
        bad = _minimal_receipt()
        bad["proven_catch"] = False
        self.assertTrue(any(self.validator.iter_errors(bad)))
        self.assertFalse(R.validate_schema(bad, require_signature=False).valid)

    def test_negative_corpus_fails_where_receipt_py_fails(self):
        for p in sorted(NEG.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(data, dict) or str(data.get("schema_version")) != "2.1":
                continue
            code_ok = R.validate_schema(data).valid
            schema_ok = not any(self.validator.iter_errors(data))
            if not code_ok:
                self.assertFalse(schema_ok, f"{p.name}: JSON Schema accepted what receipt.py rejects")


if __name__ == "__main__":
    unittest.main()
