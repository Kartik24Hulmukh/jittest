"""Regression tests for clean verify refusals at the CLI boundary."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from jittest.cli import main
from jittest.sandbox import SandboxUnavailable


class TestVerifyCliRefusalEdges(unittest.TestCase):
    def test_whitespace_test_spec_refuses_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = main([
                    "verify", "--repo", tmp, "--base", "base", "--head", "head",
                    "--test", "   ",
                ])
        self.assertEqual(rc, 2)
        self.assertIn("refused", stderr.getvalue())
        self.assertIn("test path is required", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_directory_test_path_refuses_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "tests").mkdir()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                rc = main([
                    "verify", "--repo", str(repo), "--base", "base", "--head", "head",
                    "--test", "tests",
                ])
        self.assertEqual(rc, 2)
        self.assertIn("not a regular file", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_required_sandbox_unavailable_refuses_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "test_example.py").write_text(
                "def test_example():\n    assert True\n", encoding="utf-8"
            )
            stderr = io.StringIO()
            with patch(
                "jittest.verify.verify_test",
                side_effect=SandboxUnavailable("no usable isolation backend"),
            ):
                with redirect_stderr(stderr):
                    rc = main([
                        "verify", "--repo", str(repo), "--base", "base", "--head", "head",
                        "--test", "test_example.py", "--sandbox-mode", "required",
                    ])
        self.assertEqual(rc, 2)
        self.assertIn("refused", stderr.getvalue())
        self.assertIn("no usable isolation backend", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
