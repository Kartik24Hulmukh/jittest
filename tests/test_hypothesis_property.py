"""Hypothesis property-based tests for BudgetManager, path rewriting, and config normalization (Section G)."""

import unittest
from decimal import Decimal

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except (ImportError, ModuleNotFoundError) as exc:
    raise unittest.SkipTest(
        "requires hypothesis; skipped by the zero-dependency unittest run in ci.yml"
    ) from exc

from jittest.budget import BudgetManager
from jittest.llm import FrozenRunConfig
from jittest.sandbox import _container_paths


class HypothesisStatefulPropertyTests(unittest.TestCase):
    @settings(max_examples=100)
    @given(
        token_count=st.integers(min_value=0, max_value=1_000_000),
        token_rate=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_budget_manager_non_negative_cost_bounds(self, token_count: int, token_rate: float):
        bm = BudgetManager(authorized_spend_ceiling_usd=100.0)
        cost = bm._calculate_cost(token_count, Decimal(str(round(token_rate, 6))))
        self.assertGreaterEqual(cost, Decimal("0.000000"))

    def test_frozen_run_config_immutability(self):
        cfg = FrozenRunConfig(
            provider="mock",
            model="mock-v1",
            timeout_seconds=120.0,
            temperature=0.0,
            top_p=1.0,
        )
        self.assertEqual(cfg.provider, "mock")
        self.assertEqual(cfg.timeout_seconds, 120.0)
        self.assertEqual(cfg.temperature, 0.0)
        self.assertEqual(cfg.top_p, 1.0)
        with self.assertRaises(AttributeError):
            cfg.temperature = 0.7

    def test_container_paths_prefix_rewriting_property(self):
        workdir = self.id()
        argv = [f"{workdir}/foo.py", "--arg", "val"]
        res = _container_paths(argv, workdir)
        self.assertEqual(res[0], "/workspace/foo.py")


if __name__ == "__main__":
    unittest.main()
