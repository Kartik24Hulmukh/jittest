"""Validate the frozen cohort before any payment or foreign-code execution."""
import copy
import json
import unittest
from pathlib import Path

from eval.ga73_pr_pilot import validate_manifest


class ManifestTests(unittest.TestCase):
    def test_real_manifest_and_refusals(self):
        manifest = json.loads((Path(__file__).parents[1] / 'eval/ga73_click_manifest.json').read_text())
        validate_manifest(manifest)
        for key, value in [('repo', 'https://example.com/unapproved'), ('sha', 'main'),
                           ('until', '1 day ago'), ('since', '1 year ago')]:
            broken = copy.deepcopy(manifest)
            broken[key] = value
            with self.assertRaises(ValueError):
                validate_manifest(broken)
        broken = copy.deepcopy(manifest)
        broken['pairs'][1] = broken['pairs'][0]
        with self.assertRaises(ValueError):
            validate_manifest(broken)
        broken['pairs'] = broken['pairs'][:39]
        with self.assertRaises(ValueError):
            validate_manifest(broken)

    def test_original_branch_tip_is_not_an_applied_pr_result(self):
        manifest = json.loads((Path(__file__).parents[1] / 'eval/ga73_click_manifest.json').read_text())
        broken = copy.deepcopy(manifest)
        broken['pairs'][0]['head'] = broken['pairs'][0]['pr_head']
        with self.assertRaises(ValueError):
            validate_manifest(broken)
