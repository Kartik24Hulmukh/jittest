"""Hypothesis property-based tests for BudgetManager, path rewriting, and config normalization (Section G)."""

import unittest
from decimal import Decimal
from pathlib import Path

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from jittest.budget import BudgetManager
from jittest.llm import FrozenRunConfig
from jittest.sandbox import _container_paths


class PropertyBasedTests(unittest.TestCase):
    def test_frozen_run_config_invariants(self):
        """FrozenRunConfig must remain immutable regardless of input values."""
        cfg = FrozenRunConfig()
        self.assertEqual(cfg.provider, "Mistral AI")
        self.assertEqual(cfg.model_name, "codestral-2508")
        self.assertEqual(cfg.max_attempts, 3)
        self.assertEqual(cfg.timeout_seconds, 120.0)
        self.assertEqual(cfg.temperature, 0.0)
        self.assertEqual(cfg.top_p, 1.0)
        with self.assertRaises(AttributeError):
            cfg.temperature = 0.7

    def test_container_paths_prefix_rewriting_property(self):
        """Container paths must consistently rewrite workdir prefix to /workspace."""
        workdir = Path("/home/user/project").resolve()
        argv = [str(workdir / "file.py"), "--junitxml=" + str(workdir / "report.xml"), "extra"]
        rewritten = _container_paths(argv, workdir)
        self.assertEqual(rewritten[0], "/workspace/file.py")
        self.assertEqual(rewritten[1], "--junitxml=/workspace/report.xml")
        self.assertEqual(rewritten[2], "extra")

    def test_budget_manager_cost_monotonicity(self):
        """BudgetManager cost calculation must be strictly monotonic for non-negative token counts."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.00)
        c1 = bm.calculate_cost(100, 50)
        c2 = bm.calculate_cost(200, 50)
        c3 = bm.calculate_cost(100, 100)
        self.assertGreater(c2, c1)
        self.assertGreater(c3, c1)


if HAS_HYPOTHESIS:

    class HypothesisStatefulPropertyTests(unittest.TestCase):
        @given(
            in_tok=st.integers(min_value=0, max_value=100000),
            out_tok=st.integers(min_value=0, max_value=10000),
        )
        @settings(max_examples=50)
        def test_hypothesis_cost_never_negative(self, in_tok, out_tok):
            bm = BudgetManager(authorized_spend_ceiling_usd=100.00)
            cost = bm.calculate_cost(in_tok, out_tok)
            self.assertGreaterEqual(cost, Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
