"""A completed analysis must survive a failure to talk to GitHub.

Premortem P3-13. Observed for real: CI job `catching-tests` on PR #55 ran the
full pipeline for 189 seconds against a live model and then reported FAILURE,
while the three sibling side-channels in the same function (--markdown,
--telemetry-json, GITHUB_OUTPUT) were each individually guarded. Posting the
comment was not. The consequence is the worst one this project has: a real,
proven regression is computed, paid for, and then discarded because the last
and least important step - telling a human about it - raised.

The rule these tests pin: reporting is best-effort, measurement is not.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest import cli, github

BASE_SRC = """\
def discount(price, pct):
    return price - (price * pct / 100.0)
"""

HEAD_SRC = """\
def discount(price, pct):
    return price - (price * pct / 10.0)
"""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    for var in ("GIT_DIR", "GIT_WORK_TREE"):
        env.pop(var, None)
    return subprocess.run(["git", *args], cwd=cwd, env=env,
                          capture_output=True, text=True, timeout=120)


class GhCliFallbackNeverRaises(unittest.TestCase):
    """The fallback is a fallback. A fallback that raises is worse than none."""

    def test_absent_gh_binary_is_not_an_exception(self) -> None:
        with mock.patch.object(github, "detect_pr_number", return_value="55"), \
                mock.patch.object(github.subprocess, "run",
                                  side_effect=FileNotFoundError("no gh")):
            self.assertFalse(github._gh_cli_fallback("body"))

    def test_unexecutable_gh_binary_is_not_an_exception(self) -> None:
        with mock.patch.object(github, "detect_pr_number", return_value="55"), \
                mock.patch.object(github.subprocess, "run",
                                  side_effect=PermissionError("denied")):
            self.assertFalse(github._gh_cli_fallback("body"))

    def test_a_hung_gh_invocation_is_not_an_exception(self) -> None:
        with mock.patch.object(github, "detect_pr_number", return_value="55"), \
                mock.patch.object(
                    github.subprocess, "run",
                    side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=60)):
            self.assertFalse(github._gh_cli_fallback("body"))

    def test_the_subprocess_call_is_bounded(self) -> None:
        """An unbounded post can hang a CI job forever holding a runner."""
        seen: dict[str, object] = {}

        def fake_run(*args, **kwargs):
            seen.update(kwargs)
            return subprocess.CompletedProcess(args=args, returncode=0)

        with mock.patch.object(github, "detect_pr_number", return_value="55"), \
                mock.patch.object(github.subprocess, "run", fake_run):
            self.assertTrue(github._gh_cli_fallback("body"))
        self.assertIn("timeout", seen)


class UpsertReturnsAStatusInsteadOfRaising(unittest.TestCase):
    """upsert_pr_comment's contract is 'returns a status string'. Hold it."""

    def _upsert(self, exc: BaseException) -> str:
        with mock.patch.object(github, "_token", return_value="t"), \
                mock.patch.object(github, "_request", side_effect=exc), \
                mock.patch.object(github, "_gh_cli_fallback", return_value=False):
            return github.upsert_pr_comment("body", repo="o/r", pr_number="55")

    def test_a_malformed_api_payload_is_reported_not_raised(self) -> None:
        self.assertIn("failed to comment", self._upsert(TypeError("not subscriptable")))

    def test_a_missing_id_field_is_reported_not_raised(self) -> None:
        self.assertIn("failed to comment", self._upsert(KeyError("id")))

    def test_a_socket_level_error_is_reported_not_raised(self) -> None:
        self.assertIn("failed to comment", self._upsert(OSError("connection reset")))

    def test_undecodable_json_is_reported_not_raised(self) -> None:
        self.assertIn("failed to comment", self._upsert(ValueError("bad json")))


class CompletedRunSurvivesAFailedComment(unittest.TestCase):
    """The end-to-end guarantee, through the real CLI entry point."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "repo"
        root.mkdir(parents=True)
        _git(root, "init", "-q", "-b", "main")
        (root / "pricing.py").write_text(BASE_SRC)
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "base")
        self.base = _git(root, "rev-parse", "HEAD").stdout.strip()
        (root / "pricing.py").write_text(HEAD_SRC)
        _git(root, "add", ".")
        _git(root, "commit", "-q", "-m", "head")
        self.head = _git(root, "rev-parse", "HEAD").stdout.strip()
        self.repo = root

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> int:
        return cli.main([
            "run", "--repo", str(self.repo),
            "--base", self.base, "--head", self.head,
            "--dry-run", "--comment", "--quiet",
        ])

    def test_exit_code_is_zero_when_posting_raises(self) -> None:
        with mock.patch.object(github, "upsert_pr_comment",
                               side_effect=RuntimeError("github is down")):
            self.assertEqual(self._run(), 0)

    def test_exit_code_is_zero_when_posting_raises_a_bare_exception(self) -> None:
        with mock.patch.object(github, "upsert_pr_comment",
                               side_effect=Exception("anything at all")):
            self.assertEqual(self._run(), 0)

    def test_the_failure_is_reported_rather_than_hidden(self) -> None:
        """Best-effort must not mean silent: the operator has to be told."""
        from io import StringIO
        err = StringIO()
        with mock.patch.object(github, "upsert_pr_comment",
                               side_effect=RuntimeError("github is down")), \
                mock.patch.object(sys, "stderr", err):
            self.assertEqual(self._run(), 0)
        self.assertIn("failed to comment", err.getvalue())

    def test_a_successful_post_still_reports_its_status(self) -> None:
        from io import StringIO
        err = StringIO()
        with mock.patch.object(github, "upsert_pr_comment",
                               return_value="posted new comment"), \
                mock.patch.object(sys, "stderr", err):
            self.assertEqual(self._run(), 0)
        self.assertIn("posted new comment", err.getvalue())


if __name__ == "__main__":
    unittest.main()
