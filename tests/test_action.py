"""Unit tests for jittest.action GitHub Action entrypoint module."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest.action import get_trust_context, is_test_file, run_action


class TestActionHelpers(unittest.TestCase):
    def test_is_test_file(self):
        self.assertTrue(is_test_file("test_basic.py"))
        self.assertTrue(is_test_file("app_test.py"))
        self.assertTrue(is_test_file("tests/helper.py"))
        self.assertFalse(is_test_file("app.py"))
        self.assertFalse(is_test_file("README.md"))

    def test_get_trust_context_internal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evt_file = Path(tmpdir) / "event.json"
            evt_file.write_text(json.dumps({
                "pull_request": {
                    "head": {"repo": {"full_name": "owner/repo"}},
                    "base": {"repo": {"full_name": "owner/repo"}},
                }
            }), encoding="utf-8")

            with patch.dict("os.environ", {"GITHUB_EVENT_PATH": str(evt_file)}):
                self.assertEqual(get_trust_context(), "internal")

    def test_get_trust_context_fork(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            evt_file = Path(tmpdir) / "event.json"
            evt_file.write_text(json.dumps({
                "pull_request": {
                    "head": {"repo": {"full_name": "fork_user/repo"}},
                    "base": {"repo": {"full_name": "owner/repo"}},
                }
            }), encoding="utf-8")

            with patch.dict("os.environ", {"GITHUB_EVENT_PATH": str(evt_file)}):
                self.assertEqual(get_trust_context(), "fork")

    def test_get_trust_context_unknown_when_absent(self):
        with patch.dict("os.environ", {"GITHUB_EVENT_PATH": ""}):
            self.assertEqual(get_trust_context(), "unknown")

    @patch("jittest.action.get_changed_files")
    @patch("jittest.action.upsert_pr_comment")
    def test_run_action_zero_test_changes(self, mock_comment, mock_diff):
        mock_diff.return_value = ["src/main.py", "README.md"]
        mock_comment.return_value = "posted new comment"

        code = run_action(repo_path=".", pr_number="123")
        self.assertEqual(code, 0)
        mock_comment.assert_called_once()
        self.assertIn("Zero test files modified", mock_comment.call_args[0][0])

    @patch("jittest.action.get_changed_files")
    @patch("jittest.action.upsert_pr_comment")
    @patch("jittest.action.verify_test")
    def test_run_action_sandbox_threading(self, mock_verify, mock_comment, mock_diff):
        mock_diff.return_value = ["tests/test_foo.py"]
        mock_comment.return_value = "posted"
        mock_verify.return_value = ({"verdict": "proven_catch", "disposition": "catching", "proven_catch": True, "wall_clock_s": 1.0}, 0)

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_foo.py"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("def test_dummy(): pass\n", encoding="utf-8")

            # 1. Explicit override 'required'
            run_action(repo_path=tmpdir, sandbox_override="required")
            self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 2. Fork context with empty override -> 'required'
            with patch("jittest.action.get_trust_context", return_value="fork"):
                run_action(repo_path=tmpdir, sandbox_override="")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 3. Internal context with empty override -> 'auto'
            with patch("jittest.action.get_trust_context", return_value="internal"):
                run_action(repo_path=tmpdir, sandbox_override="")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "auto")

            # 4. Fork context with sandbox_override="auto" -> 'required'
            with patch("jittest.action.get_trust_context", return_value="fork"):
                run_action(repo_path=tmpdir, sandbox_override="auto")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 5. Unknown context with sandbox_override="auto" -> 'required'
            with patch("jittest.action.get_trust_context", return_value="unknown"):
                run_action(repo_path=tmpdir, sandbox_override="auto")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 6. Internal context with sandbox_override="auto" -> 'auto'
            with patch("jittest.action.get_trust_context", return_value="internal"):
                run_action(repo_path=tmpdir, sandbox_override="auto")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "auto")

            # 7. Fork context cannot downgrade to 'off' -> enforced 'required'
            with patch("jittest.action.get_trust_context", return_value="fork"):
                run_action(repo_path=tmpdir, sandbox_override="off")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 8. Unknown context cannot downgrade to 'off' -> enforced 'required'
            with patch("jittest.action.get_trust_context", return_value="unknown"):
                run_action(repo_path=tmpdir, sandbox_override="off")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 9. Internal context with 'off' -> 'off'
            with patch("jittest.action.get_trust_context", return_value="internal"):
                run_action(repo_path=tmpdir, sandbox_override="off")
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "off")

            # 10. JITTEST_SANDBOX_MODE="auto" from env (e.g. YAML default) in fork context -> 'required'
            with patch.dict(os.environ, {"JITTEST_SANDBOX_MODE": "auto"}), patch(
                "jittest.action.get_trust_context", return_value="fork"
            ):
                run_action(repo_path=tmpdir, sandbox_override=None)
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 11. JITTEST_SANDBOX_MODE="auto" from env in unknown context -> 'required'
            with patch.dict(os.environ, {"JITTEST_SANDBOX_MODE": "auto"}), patch(
                "jittest.action.get_trust_context", return_value="unknown"
            ):
                run_action(repo_path=tmpdir, sandbox_override=None)
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

            # 12. JITTEST_SANDBOX_MODE="auto" from env in internal context -> 'auto'
            with patch.dict(os.environ, {"JITTEST_SANDBOX_MODE": "auto"}), patch(
                "jittest.action.get_trust_context", return_value="internal"
            ):
                run_action(repo_path=tmpdir, sandbox_override=None)
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "auto")

            # 13. JITTEST_SANDBOX_MODE="off" from env in fork context -> enforced 'required'
            with patch.dict(os.environ, {"JITTEST_SANDBOX_MODE": "off"}), patch(
                "jittest.action.get_trust_context", return_value="fork"
            ):
                run_action(repo_path=tmpdir, sandbox_override=None)
                self.assertEqual(mock_verify.call_args[1]["sandbox_mode"], "required")

    @patch("jittest.action.get_changed_files")
    @patch("jittest.action.upsert_pr_comment")
    @patch("jittest.action.verify_test")
    def test_run_action_policy_matrix(self, mock_verify, mock_comment, mock_diff):
        mock_diff.return_value = ["tests/test_foo.py"]
        mock_comment.return_value = "posted"

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "tests" / "test_foo.py"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("def test_dummy(): pass\n", encoding="utf-8")

            # Case A: Proven catch
            mock_verify.return_value = ({"verdict": "proven_catch", "disposition": "catching", "proven_catch": True, "wall_clock_s": 1.0}, 0)
            self.assertEqual(run_action(repo_path=tmpdir, policy="advisory"), 0)
            self.assertEqual(run_action(repo_path=tmpdir, policy="strict"), 0)
            self.assertEqual(run_action(repo_path=tmpdir, policy="block-on-refusal"), 0)

            # Case B: Non-discriminating / Refuted (no catch, clean run)
            mock_verify.return_value = ({"verdict": "refuted", "disposition": "latent_failure", "proven_catch": False, "wall_clock_s": 1.0}, 1)
            self.assertEqual(run_action(repo_path=tmpdir, policy="advisory"), 0)
            self.assertEqual(run_action(repo_path=tmpdir, policy="strict"), 1)
            self.assertEqual(run_action(repo_path=tmpdir, policy="block-on-refusal"), 0)

            # Case C: Refusal (ENV_SETUP_FAILED / uncollectable)
            mock_verify.return_value = ({"verdict": "inconclusive", "disposition": "ENV_SETUP_FAILED", "proven_catch": False, "wall_clock_s": 0.0}, 1)
            self.assertEqual(run_action(repo_path=tmpdir, policy="advisory"), 0)
            self.assertEqual(run_action(repo_path=tmpdir, policy="strict"), 1)
            self.assertEqual(run_action(repo_path=tmpdir, policy="block-on-refusal"), 1)

