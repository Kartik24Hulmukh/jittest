import subprocess
import sys
import unittest
from pathlib import Path


class VersionDriftTest(unittest.TestCase):
    def test_versions_agree(self):
        script = Path(__file__).resolve().parent.parent / "scripts" / "check_version_drift.py"
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
