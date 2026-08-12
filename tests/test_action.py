"""Unit tests for jittest.action GitHub Action entrypoint module."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest.action import is_fork_pr, is_test_file, run_action


class TestActionHelpers(unittest.TestCase):
    def test_is_test_file(self):
        self.assertTrue(is_test_file("test_basic.py"))
        self.assertTrue(is_test_file("app_test.py"))
        self.assertTrue(is_test_file("tests/helper.py"))
        self.assertFalse(is_test_file("app.py"))
        self.assertFalse(is_test_file("README.md"))

    def test_is_fork_pr_false_when_same_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evt_file = Path(tmpdir) / "event.json"
            evt_file.write_text(json.dumps({
                "pull_request": {
                    "head": {"repo": {"full_name": "owner/repo"}},
                    "base": {"repo": {"full_name": "owner/repo"}},
                }
            }), encoding="utf-8")

            with patch.dict("os.environ", {"GITHUB_EVENT_PATH": str(evt_file)}):
                self.assertFalse(is_fork_pr())

    def test_is_fork_pr_true_when_external_fork(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evt_file = Path(tmpdir) / "event.json"
            evt_file.write_text(json.dumps({
                "pull_request": {
                    "head": {"repo": {"full_name": "fork_user/repo"}},
                    "base": {"repo": {"full_name": "owner/repo"}},
                }
            }), encoding="utf-8")

            with patch.dict("os.environ", {"GITHUB_EVENT_PATH": str(evt_file)}):
                self.assertTrue(is_fork_pr())

    @patch("jittest.action.get_changed_files")
    @patch("jittest.action.upsert_pr_comment")
    def test_run_action_zero_test_changes(self, mock_comment, mock_diff):
        mock_diff.return_value = ["src/main.py", "README.md"]
        mock_comment.return_value = "posted new comment"

        code = run_action(repo_path=".", pr_number="123")
        self.assertEqual(code, 0)
        mock_comment.assert_called_once()
        self.assertIn("Zero test files modified", mock_comment.call_args[0][0])
