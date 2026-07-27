"""Regression tests for Defect 29: reporting a finding could destroy it.

By the time jittest writes a side channel it has already done the expensive,
valuable work: found a risky changed symbol, generated a candidate test, run it
on both revisions, confirmed it passes on base and fails on head, reran it to
rule out flakiness, and had an assessor judge it a real regression.

Then it wrote `GITHUB_OUTPUT`, or a `--markdown` file, or a `--telemetry-json`
file, unguarded. If that path was not writable - a read-only mount, a stale
`GITHUB_OUTPUT` from a cancelled job, a `--markdown` path inside a directory
that does not exist, a full disk - the process raised OSError and exited
non-zero. The user saw a crash, not a regression. The act of reporting the
finding destroyed the finding.

A failure to write a convenience artifact is never a reason to discard a proven
result. All three writes now warn and continue.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

# A path that cannot be created or written on Linux CI runners.
UNWRITABLE = "/proc/does-not-exist/jittest-output"


def run_cli(args, env_extra=None, cwd=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.pop("JITTEST_API_KEY", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "jittest.cli", *args],
        capture_output=True, text=True, errors="replace", env=env,
        cwd=str(cwd or REPO_ROOT), timeout=300,
    )


class TestUnwritableSideChannels(unittest.TestCase):
    """An unwritable side channel must warn, not crash."""

    def assert_no_crash(self, proc, expected_warning):
        combined = proc.stdout + proc.stderr
        self.assertNotIn("Traceback (most recent call last)", combined,
                         f"crashed instead of warning:\n{combined[-2000:]}")
        self.assertIn(expected_warning, combined,
                      f"no warning emitted:\n{combined[-2000:]}")

    def test_unwritable_github_output_is_a_warning(self):
        proc = run_cli(["run", "--dry-run"],
                       {"GITHUB_OUTPUT": UNWRITABLE})
        self.assert_no_crash(proc, "could not write GITHUB_OUTPUT")

    def test_unwritable_markdown_path_is_a_warning(self):
        proc = run_cli(["run", "--dry-run", "--markdown", UNWRITABLE])
        self.assert_no_crash(proc, "could not write markdown")

    def test_unwritable_telemetry_path_is_a_warning(self):
        proc = run_cli(["run", "--dry-run", "--telemetry-json", UNWRITABLE])
        self.assert_no_crash(proc, "could not write telemetry")

    def test_writable_github_output_still_receives_keys(self):
        """The guard must not silently swallow the normal, working path."""
        out = Path(tempfile.mkdtemp()) / "github_output"
        out.write_text("", encoding="utf-8")
        proc = run_cli(["run", "--dry-run"], {"GITHUB_OUTPUT": str(out)})
        written = out.read_text(encoding="utf-8")
        self.assertNotIn("could not write GITHUB_OUTPUT", proc.stdout + proc.stderr)
        for key in ("regressions=", "findings=", "cost_usd="):
            self.assertIn(key, written, f"{key} missing from GITHUB_OUTPUT")


if __name__ == "__main__":
    unittest.main()
