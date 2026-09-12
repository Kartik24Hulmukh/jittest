"""``python -m jittest`` must behave exactly like the ``jittest`` console script."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

import jittest

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=SRC)
    return subprocess.run(
        [sys.executable, "-m", "jittest", *args],
        capture_output=True, text=True, env=env, timeout=60,
    )


class ModuleEntrypointTest(unittest.TestCase):
    def test_version_matches_package(self) -> None:
        proc = _run("--version")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(jittest.__version__, proc.stdout + proc.stderr)

    def test_help_lists_subcommands(self) -> None:
        proc = _run("--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for sub in ("run", "verify", "doctor", "explain"):
            self.assertIn(sub, proc.stdout)

    def test_no_command_is_a_usage_error(self) -> None:
        proc = _run()
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
