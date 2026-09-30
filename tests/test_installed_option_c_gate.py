"""Offline gate contract, explicitly not a real-daemon execution proof."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstalledOptionCGate(unittest.TestCase):
    def test_no_daemon_is_not_run_and_nonzero_with_record(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            wheel = work / "placeholder.whl"
            wheel.write_bytes(b"inert placeholder, never installed")
            out = work / "proof.json"
            env = os.environ.copy()
            env["PATH"] = str(work / "empty-bin")
            result = subprocess.run([
                sys.executable, str(ROOT / "scripts/prove_installed_option_c.py"),
                "--wheel", str(wheel), "--image", "python@sha256:" + "a" * 64,
                "--out", str(out),
            ], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 1, result.stderr)
            record = json.loads(out.read_text())
            self.assertEqual(record["status"], "NOT_RUN")
            self.assertFalse(record["passed"])

    def test_workflow_requires_real_registry_and_retains_failed_proof(self):
        text = (ROOT / ".github/workflows/option-c-proof.yml").read_text()
        job = text.split("\n  installed-wheel:\n", 1)[1]
        self.assertIn("needs: registry-live", job)
        self.assertIn("prove_installed_option_c.py", job)
        self.assertIn('d["verified"] is True', job)
        self.assertIn("if: always()", job)