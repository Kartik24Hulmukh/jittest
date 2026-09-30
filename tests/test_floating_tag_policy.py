"""Offline prerelease tag policy; no tags, pushes or publication are performed."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('floating_tag_policy', ROOT / 'scripts/check_floating_tag.py')
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class FloatingTagPolicy(unittest.TestCase):
    def test_only_canonical_final_v0_releases_advance(self):
        for tag in ('v0.4.1', 'v0.5.0', 'v0.12.234'):
            self.assertTrue(POLICY.stable_v0_tag('refs/tags/' + tag))
        for tag in ('v0.5.0rc1', 'v0.5.0-rc.1', 'v0.5.0.dev1', 'v0.5.0a1',
                    'v0.5.0b1', 'v0.5.0+local', 'v0.5.0.post1', 'v0.05.0', 'v1.0.0', 'v0'):
            with self.subTest(tag=tag):
                self.assertFalse(POLICY.stable_v0_tag('refs/tags/' + tag))
        self.assertFalse(POLICY.stable_v0_tag('refs/heads/v0.5.0'))

    def test_force_update_is_guarded_by_actual_policy_output(self):
        workflow = (ROOT / '.github/workflows/release.yml').read_text()
        job = workflow.split('  update-floating-tag:', 1)[1]
        self.assertIn('python scripts/check_floating_tag.py "$GITHUB_REF"', job)
        action = job.split('- name: Force-update v0 tag to this commit', 1)[1]
        self.assertIn("if: steps.release-channel.outputs.stable == 'true'", action)
        self.assertIn('needs: [verify-published, github-release]', job)

    def test_actual_script_emits_false_for_prerelease(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / 'output'
            env = dict(os.environ, GITHUB_OUTPUT=str(output))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/check_floating_tag.py'),
                                     'refs/tags/v0.5.0rc1'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), 'stable=false\n')
