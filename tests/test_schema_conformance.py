"""Schema conformance test for JitTest evidence receipts.

Validates that emitted evidence receipts strictly conform to docs/SCHEMA.md:
- Mandatory top-level fields exist and match expected types.
- Verdict is one of the 6 valid verdict classes.
- proven_catch boolean invariant holds (True iff proven_catch or reproduction_catch).
- Provenance object exists and has valid metadata.
- Signature block carries valid verifying_key and algorithm.
"""

import tempfile
import unittest
from pathlib import Path

from jittest.receipt import sign_evidence
from jittest.verify import VerdictClass


class TestSchemaConformance(unittest.TestCase):
    def test_emitted_receipt_conforms_to_schema_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "signing_key.pem"
            evidence_data = {
                "schema_version": "2.0",
                "tool": "jittest verify",
                "verdict": VerdictClass.PROVEN_CATCH,
                "proven_catch": True,
                "disposition": "catching",
                "provenance": {
                    "repo_path": "/workspace/repo",
                    "base_sha": "a" * 40,
                    "head_sha": "b" * 40,
                    "test_file_name": "test_sample.py",
                    "test_file_sha256": "c" * 64,
                    "tool_commit_sha": "d" * 40,
                    "tool_branch": "main",
                    "tool_dirty": False,
                    "tool_tree_sha": "e" * 40,
                    "rel_path": ".",
                },
                "sandbox": {
                    "mode": "required",
                    "backend": "docker",
                },
                "base_execution": {"exit_code": 0, "duration_s": 0.1},
                "head_execution": {"exit_code": 1, "duration_s": 0.1},
                "rerun_agreement": True,
                "wall_clock_s": 1.23,
                "provider_cost_usd": 0.0,
            }
            signed = sign_evidence(evidence_data, key_path=key_path)

            # 1. Top-Level Mandatory Fields
            required_top = [
                ("schema_version", str),
                ("tool", str),
                ("verdict", str),
                ("proven_catch", bool),
                ("disposition", str),
                ("provenance", dict),
                ("sandbox", dict),
                ("base_execution", dict),
                ("head_execution", dict),
                ("wall_clock_s", (int, float)),
                ("signature", dict),
            ]
            for field, expected_type in required_top:
                self.assertIn(field, signed, f"Missing required top-level field: {field}")
                self.assertIsInstance(
                    signed[field], expected_type,
                    f"Field {field} should be {expected_type}, got {type(signed[field])}"
                )

            # 2. Schema version and tool contract
            self.assertEqual(signed["schema_version"], "2.0")
            self.assertEqual(signed["tool"], "jittest verify")

            # 3. Verdict enum and proven_catch invariant
            valid_verdicts = {
                "proven_catch",
                "reproduction_catch",
                "collection_catch",
                "refuted",
                "non_discriminating",
                "inconclusive",
            }
            self.assertIn(signed["verdict"], valid_verdicts)
            expected_pc = signed["verdict"] in ("proven_catch", "reproduction_catch")
            self.assertEqual(signed["proven_catch"], expected_pc)

            # 4. Provenance Object
            prov = signed["provenance"]
            required_prov = [
                ("repo_path", str),
                ("base_sha", str),
                ("head_sha", str),
                ("test_file_name", str),
                ("test_file_sha256", str),
            ]
            for field, expected_type in required_prov:
                self.assertIn(field, prov, f"Missing required provenance field: {field}")
                self.assertIsInstance(prov[field], expected_type)

            # 5. Signature Block
            sig = signed["signature"]
            self.assertEqual(sig.get("algorithm"), "Ed25519")
            self.assertTrue(bool(sig.get("verifying_key") or sig.get("public_key")))
            self.assertIn("value", sig)


if __name__ == "__main__":
    unittest.main()