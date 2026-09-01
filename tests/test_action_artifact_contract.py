"""Regression tests for the public composite Action contract."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestActionArtifactContract(unittest.TestCase):
    def test_custom_output_directory_is_uploaded(self):
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn("JITTEST_OUTPUT_DIR: ${{ inputs.output-dir }}", action)
        self.assertIn("path: ${{ inputs.output-dir }}/", action)
        self.assertNotIn("path: jittest-evidence/", action)

    def test_missing_evidence_is_not_silently_ignored(self):
        action = (ROOT / "action.yml").read_text(encoding="utf-8")
        self.assertIn("if-no-files-found: warn", action)
        self.assertNotIn("if-no-files-found: ignore", action)

    def test_quickstart_keeps_untrusted_prs_fail_closed(self):
        quickstart = (ROOT / "docs" / "QUICKSTART.md").read_text(encoding="utf-8")
        self.assertIn("persist-credentials: false", quickstart)
        self.assertIn('sandbox-mode: "required"', quickstart)
        self.assertIn('policy: "advisory"', quickstart)
        self.assertNotIn("@v0.3.2", quickstart)


if __name__ == "__main__":
    unittest.main()
