"""Keep the no-dependency discovery lane independent of local dev packages."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class SwarmOptionalDependencyTests(unittest.TestCase):
    def test_discovery_without_site_packages(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root / "src"))
        result = subprocess.run(
            [sys.executable, "-S", "-c", """
import importlib.util
import unittest
assert importlib.util.find_spec('hypothesis') is None
suite = unittest.defaultTestLoader.discover(
    'tests', pattern='test_persona_swarm_100x.py', top_level_dir='.'
)
assert not unittest.defaultTestLoader.errors, unittest.defaultTestLoader.errors
assert suite.countTestCases() == 6, suite.countTestCases()
"""],
            cwd=root, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
