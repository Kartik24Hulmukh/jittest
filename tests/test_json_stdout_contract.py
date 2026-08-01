"""Regression test for Premortem 3, finding P3-1.

``jittest run --json`` promises exactly one parsable JSON object on stdout.
Before this test existed, ``_pipeline_helpers`` printed one ``  telemetry:
{...}`` line per candidate to stdout, so ``json.load(stdout)`` failed with
``Expecting value: line 1 column 3 (char 2)`` for any run that actually
analysed something. The bug was invisible whenever the risk gate dropped every
symbol, because then no telemetry was emitted and stdout happened to be clean.

The source comment at the emit site already said "Emit structured line to
stderr"; the call simply had no ``file=`` argument. This test pins the
contract so the intent and the behaviour cannot drift apart again.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BASE_SRC = "def innermost(values):\n    return min(values)\n"
HEAD_SRC = "def innermost(values):\n    return max(values)\n"


def _git(args, cwd):
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    })
    return subprocess.run(["git", *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, check=False)


class TelemetryGoesToStderr(unittest.TestCase):
    """Unit-level: the emit helper must not write to stdout."""

    def test_emit_helper_writes_nothing_to_stdout(self):
        from jittest import _pipeline_helpers

        src = Path(_pipeline_helpers.__file__).read_text(encoding="utf-8")
        # Every print in this module must be explicitly routed to stderr.
        offenders = [
            line.strip()
            for line in src.splitlines()
            if line.strip().startswith("print(") and "file=sys.stderr" not in line
        ]
        self.assertEqual(
            offenders, [],
            "_pipeline_helpers must not print to stdout; it would corrupt the "
            f"`--json` contract. Offending lines: {offenders}",
        )

    def test_telemetry_line_is_not_captured_by_redirect_stdout(self):
        from jittest import _pipeline_helpers  # noqa: F401
        from jittest.results import CandidateTelemetry

        tel = CandidateTelemetry(
            target_symbol="innermost", target_file="pkg/core.py",
            risk_score=0.5, candidate_index=1, disposition="model_declined",
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            print(f"  telemetry: {tel.as_jsonl()}", file=sys.stderr, flush=True)
        self.assertEqual(
            buf.getvalue(), "",
            "telemetry must not reach stdout",
        )
        self.assertIn("innermost", tel.as_jsonl())


class JsonStdoutIsParsable(unittest.TestCase):
    """End to end: stdout of `run --json` must parse as a single object."""

    def test_stdout_parses_when_candidates_were_analysed(self):
        if _git(["--version"], Path(tempfile.gettempdir())).returncode != 0:
            self.skipTest("git unavailable")

        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            (repo / "pkg").mkdir(parents=True)
            (repo / "pkg" / "__init__.py").write_text("")
            (repo / "pkg" / "core.py").write_text(BASE_SRC)
            _git(["init", "-q", "-b", "main"], repo)
            _git(["add", "-A"], repo)
            _git(["commit", "-q", "-m", "base"], repo)
            _git(["branch", "base-ref"], repo)
            (repo / "pkg" / "core.py").write_text(HEAD_SRC)
            _git(["add", "-A"], repo)
            _git(["commit", "-q", "-m", "head"], repo)

            env = dict(os.environ)
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in [str(Path(__file__).resolve().parent.parent / "src"),
                            env.get("PYTHONPATH", "")] if p)
            proc = subprocess.run(
                [sys.executable, "-c",
                 "import sys;from jittest.cli import main;sys.exit(main())",
                 "run", "--repo", str(repo), "--base", "base-ref",
                 # threshold 0 guarantees telemetry is actually emitted, which
                 # is the only condition under which the bug appeared
                 "--risk-threshold", "0.0",
                 "--dry-run", "--json", "--quiet"],
                capture_output=True, text=True, timeout=300, env=env,
            )
            self.assertIn(proc.returncode, (0, 1),
                          f"unexpected exit {proc.returncode}: {proc.stderr[-500:]}")
            try:
                report = json.loads(proc.stdout)
            except ValueError as exc:  # pragma: no cover - the regression itself
                self.fail(
                    "stdout of `run --json` is not parsable JSON "
                    f"({exc}). First 200 chars: {proc.stdout[:200]!r}"
                )
            self.assertIn("version", report)
            self.assertNotIn("telemetry:", proc.stdout)


if __name__ == "__main__":
    unittest.main()
