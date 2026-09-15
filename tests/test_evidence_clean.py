"""Regression tests for the post-suite evidence integrity guard (#210)."""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_evidence_clean  # noqa: E402


class EvidenceCleanTest(unittest.TestCase):
    def test_clean_checkout_passes(self):
        with patch.object(
            check_evidence_clean.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "", ""),
        ) as run:
            self.assertEqual(check_evidence_clean.main(), 0)
            args = run.call_args.args[0]
            self.assertIn("--untracked-files=all", args)
            self.assertIn("docs/evidence", args)
            self.assertIn("jittest-evidence", args)

    def test_modified_deleted_and_untracked_receipts_fail(self):
        for status in [" M", "M ", " D", "??"]:
            with (
                self.subTest(status=status),
                patch.object(
                    check_evidence_clean.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(
                        [], 0, status + " jittest-evidence/x.json\n", ""
                    ),
                ),
            ):
                self.assertEqual(check_evidence_clean.main(), 1)

    def test_git_error_fails_closed(self):
        with patch.object(
            check_evidence_clean.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 128, "", "not a repository"),
        ):
            self.assertEqual(check_evidence_clean.main(), 1)
