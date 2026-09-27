"""eval/preflight_model.py: a retired model is refused before any spend."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.preflight_model import check  # noqa: E402


class PreflightModel(unittest.TestCase):
    def test_served_model_passes(self):
        ok, _ = check("z-ai/x-5.3", ["z-ai/x-5.3", "meta/y"])
        self.assertTrue(ok)

    def test_retired_model_fails_and_names_successors(self):
        ok, msg = check("z-ai/x-5.2", ["z-ai/x-5.3", "meta/y"])
        self.assertFalse(ok)
        self.assertIn("z-ai/x-5.3", msg)
        self.assertNotIn("meta/y", msg)

    def test_unlistable_catalogue_is_not_guessed(self):
        ok, msg = check("z-ai/x-5.2", None)
        self.assertTrue(ok)
        self.assertIn("not verified", msg)


if __name__ == "__main__":
    unittest.main()
