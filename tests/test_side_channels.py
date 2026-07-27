"""Regression tests for Defect 29: side-channel writes could kill a good run.

The run had already completed, the oracle had already proven a regression, and
the assessor had already approved it - and then jittest crashed with an
unhandled OSError because the *reporting side channel* was not writable:
GITHUB_OUTPUT pointing at a path that no longer exists, a read-only artifact
directory, a full disk. On a CI runner that turns a successful analysis into a
red build with a traceback, which is exactly the behaviour that gets a tool
removed from a repository.

The rule this file locks in: a failure to *write about* the result must never
destroy the result. Every optional output path degrades to a warning.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, errors="replace",
    )


class TestUnwritableSideChannels(unittest.TestCase):
    """Optional outputs degrade to warnings; the run still exits cleanly."""

    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp())
        _git(cls.repo, "init", "-q", "-b", "main", ".")
        _git(cls.repo, "config", "user.email", "t@x.dev")
        _git(cls.repo, "config", "user.name", "t")
        _git(cls.repo, "config", "commit.gpgsign", "false")
        (cls.repo / "money.py").write_text(
            "def apply_discount(price, pct):\n"
            "    return max(0.0, price - price * pct / 100.0)\n",
            encoding="utf-8",
        )
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "base")
        cls.base = _git(cls.repo, "rev-parse", "HEAD").stdout.strip()
        (cls.repo / "money.py").write_text(
            "def apply_discount(price, pct):\n"
            "    return price - price * pct / 100.0\n",
            encoding="utf-8",
        )
        _git(cls.repo, "add", "-A")
        _git(cls.repo, "commit", "-qm", "head")
        cls.head = _git(cls.repo, "rev-parse", "HEAD").stdout.strip()

    def _run(self, extra_env=None, extra_args=()):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SRC)
        env.pop("JITTEST_API_KEY", None)
        env.pop("GITHUB_OUTPUT", None)
        env.update(extra_env or {})
        proc = subprocess.run(
            [sys.executable, "-m", "jittest.cli", "run",
             "--repo", str(self.repo), "--base", self.base,
             "--head", self.head, "--dry-run", *extra_args],
            capture_output=True, text=True, errors="replace", env=env,
            timeout=300,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_unwritable_github_output_is_a_warning(self):
        rc, out = self._run(
            {"GITHUB_OUTPUT": "/proc/does-not-exist/github_output.txt"})
        self.assertNotIn("Traceback (most recent call last)", out)
        self.assertIn("could not write GITHUB_OUTPUT", out)
        self.assertEqual(rc, 0)

    def test_unwritable_markdown_path_is_a_warning(self):
        rc, out = self._run(
            extra_args=("--markdown", "/proc/does-not-exist/report.md"))
        self.assertNotIn("Traceback (most recent call last)", out)
        self.assertIn("could not write markdown", out)
        self.assertEqual(rc, 0)

    def test_unwritable_telemetry_path_is_a_warning(self):
        rc, out = self._run(
            extra_args=("--telemetry-json", "/proc/does-not-exist/tel.jsonl"))
        self.assertNotIn("Traceback (most recent call last)", out)
        self.assertIn("could not write telemetry", out)
        self.assertEqual(rc, 0)

    def test_writable_github_output_still_receives_keys(self):
        out_file = Path(tempfile.mkdtemp()) / "gh_out.txt"
        rc, _ = self._run({"GITHUB_OUTPUT": str(out_file)})
        self.assertEqual(rc, 0)
        written = out_file.read_text(encoding="utf-8")
        for key in ("regressions=", "findings=", "cost_usd="):
            self.assertIn(key, written)


if __name__ == "__main__":
    unittest.main()
