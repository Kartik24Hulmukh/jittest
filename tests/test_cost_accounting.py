"""Lint probe: price resolution and token estimation only."""
from __future__ import annotations

import os
import unittest

from jittest.llm import PRICES, estimate_tokens, price_for


class _EnvGuard(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("JITTEST_MODEL_PRICE")
        os.environ.pop("JITTEST_MODEL_PRICE", None)

    def tearDown(self):
        os.environ.pop("JITTEST_MODEL_PRICE", None)
        if self._old is not None:
            os.environ["JITTEST_MODEL_PRICE"] = self._old


class PriceResolution(_EnvGuard):
    def test_known_models_keep_their_price(self):
        self.assertEqual(price_for("claude-sonnet-4-5"), PRICES["claude-sonnet-4-5"])

    def test_unknown_models_are_not_guessed(self):
        self.assertIsNone(price_for("glm-5.2"))
        self.assertIsNone(price_for("z-ai/glm-5.2"))

    def test_an_operator_may_state_a_price(self):
        os.environ["JITTEST_MODEL_PRICE"] = "0.60,2.20"
        self.assertEqual(price_for("z-ai/glm-5.2"), (0.60, 2.20))

    def test_a_stated_price_beats_the_builtin_table(self):
        os.environ["JITTEST_MODEL_PRICE"] = "1,2"
        self.assertEqual(price_for("claude-sonnet-4-5"), (1.0, 2.0))

    def test_a_malformed_price_is_ignored_rather_than_crashing_the_run(self):
        for bad in ("cheap", "1", "1,2,3", "", "   ", "-1,2"):
            os.environ["JITTEST_MODEL_PRICE"] = bad
            self.assertIsNone(price_for("z-ai/glm-5.2"), bad)

    def test_a_slash_separator_is_accepted_because_people_will_type_it(self):
        os.environ["JITTEST_MODEL_PRICE"] = "0.5/1.5"
        self.assertEqual(price_for("anything"), (0.5, 1.5))


class TokenEstimation(unittest.TestCase):
    def test_the_estimate_is_never_zero_for_real_text(self):
        self.assertGreaterEqual(estimate_tokens("hello"), 1)

    def test_empty_input_still_costs_something_rather_than_nothing(self):
        self.assertEqual(estimate_tokens(""), 1)

    def test_the_estimate_scales_with_length(self):
        short = estimate_tokens("x" * 100)
        long = estimate_tokens("x" * 10000)
        self.assertGreater(long, short * 50)
