"""Valid TOML nonfinite numbers must retain established config fallback semantics."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest.config import Config, load_config, normalise_values


class NonfiniteIntegerConfig(unittest.TestCase):
    def test_toml_integer_settings_fall_back_with_notes(self):
        for key in ('timeout_s', 'reruns'):
            for literal in ('inf', '-inf', 'nan'):
                with self.subTest(key=key, literal=literal), tempfile.TemporaryDirectory() as d:
                    root = Path(d)
                    (root / 'pyproject.toml').write_text(f'[tool.jittest]\n{key} = {literal}\n')
                    with patch.dict(os.environ, {}, clear=True):
                        cfg = load_config(root)
                    self.assertEqual(getattr(cfg, key), getattr(Config(), key))
                    self.assertTrue(any(key in note for note in cfg.notes))
                    json.dumps(cfg.as_dict(), allow_nan=False)

    def test_all_integer_settings_reject_nonfinite_conversion(self):
        for key in ('max_targets', 'candidates_per_target', 'timeout_s', 'reruns', 'repair_attempts'):
            for value in (float('inf'), float('-inf'), float('nan')):
                with self.subTest(key=key, value=value):
                    clean, notes = normalise_values({key: value})
                    self.assertEqual(clean[key], getattr(Config(), key))
                    self.assertTrue(notes)

    def test_finite_clamp_and_budget_policy_unchanged(self):
        clean, notes = normalise_values({'reruns': -2, 'timeout_s': 99999,
                                        'budget_usd': float('nan')})
        self.assertEqual(clean, {'reruns': 0, 'timeout_s': 3600, 'budget_usd': 1.0})
        self.assertEqual(len(notes), 3)
