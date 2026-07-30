"""Lint probe: response accounting only."""
from __future__ import annotations

import os
import unittest

from jittest.llm import Usage


class _EnvGuard(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("JITTEST_MODEL_PRICE")
        os.environ.pop("JITTEST_MODEL_PRICE", None)

    def tearDown(self):
        os.environ.pop("JITTEST_MODEL_PRICE", None)
        if self._old is not None:
            os.environ["JITTEST_MODEL_PRICE"] = self._old


class _Accountant:
    def __init__(self, model):
        from jittest.llm import BaseLLM, HTTPLLM
        self.model = model
        self.model_name = model.split("/")[-1]
        self.usage = Usage()
        self._price = HTTPLLM._price.__get__(self)
        self._account = HTTPLLM._account.__get__(self)
        self._account_response = HTTPLLM._account_response.__get__(self)
        assert issubclass(HTTPLLM, BaseLLM)


class Accounting(_EnvGuard):
    def test_reported_tokens_are_used_verbatim(self):
        a = _Accountant("claude-sonnet-4-5")
        a._account_response(1000, 2000, "prompt", "response")
        self.assertEqual(a.usage.input_tokens, 1000)
        self.assertEqual(a.usage.output_tokens, 2000)
        self.assertFalse(a.usage.tokens_estimated)
        self.assertAlmostEqual(a.usage.cost_usd, 0.003 + 0.030, places=6)

    def test_a_missing_usage_block_is_estimated_not_treated_as_zero(self):
        a = _Accountant("claude-sonnet-4-5")
        a._account_response(None, None, "p" * 4000, "r" * 400)
        self.assertTrue(a.usage.tokens_estimated)
        self.assertGreater(a.usage.input_tokens, 900)
        self.assertGreater(a.usage.cost_usd, 0.0)

    def test_garbage_in_the_usage_block_does_not_crash_the_run(self):
        a = _Accountant("claude-sonnet-4-5")
        a._account_response("lots", {"nested": 1}, "p" * 40, "r" * 40)
        self.assertTrue(a.usage.tokens_estimated)
        self.assertEqual(a.usage.calls, 1)

    def test_an_unpriced_model_still_counts_tokens(self):
        a = _Accountant("z-ai/glm-5.2")
        a._account_response(1500, 500, "p", "r")
        self.assertFalse(a.usage.priced)
        self.assertEqual(a.usage.cost_usd, 0.0)
        self.assertEqual(a.usage.input_tokens + a.usage.output_tokens, 2000)

    def test_stating_a_price_restores_the_dollar_cap_for_that_model(self):
        os.environ["JITTEST_MODEL_PRICE"] = "1.00,3.00"
        a = _Accountant("z-ai/glm-5.2")
        a._account_response(1_000_000, 1_000_000, "p", "r")
        self.assertTrue(a.usage.priced)
        self.assertAlmostEqual(a.usage.cost_usd, 4.00, places=6)
