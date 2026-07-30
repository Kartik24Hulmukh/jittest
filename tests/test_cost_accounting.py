"""A run whose cost is unknown must still be measurable.

The gap this closes is narrow and it has bitten this project directly. The
model in use here, `z-ai/glm-5.2` behind an NVIDIA-hosted endpoint, is not in
the built-in price table. Before this change that had two consequences, and
only the first was intended:

1. The dollar cap was replaced by a request-count ceiling. That is correct.
   Guessing a price would produce a confident wrong number in a cost report,
   which is worse than admitting ignorance.
2. The run reported `cost_usd: 0.0` and no token counts at all. That is not
   admitting ignorance, it is reporting zero - and zero is a number people
   act on. The eval harness averages `cost_usd`, so an unpriced model would
   quietly pull the mean cost per pull request toward zero.

So: always count tokens, price them when a price is known or stated, and label
the difference between a measured token count and an estimated one.
"""
from __future__ import annotations

import os
import unittest

from jittest.llm import PRICES, Usage, estimate_tokens, price_for
from jittest.pipeline import Report


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
        """Providers discount. The operator paying the bill is the authority."""
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
        # A request was issued. Reporting zero tokens for it would understate
        # the run, and the guard would never trip.
        self.assertEqual(estimate_tokens(""), 1)

    def test_the_estimate_scales_with_length(self):
        short = estimate_tokens("x" * 100)
        long = estimate_tokens("x" * 10000)
        self.assertGreater(long, short * 50)


class _Accountant:
    """The accounting half of HTTPLLM, without the network half."""

    def __init__(self, model):
        from jittest.llm import HTTPLLM, BaseLLM
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
        # 1000 in at $3/Mtok + 2000 out at $15/Mtok
        self.assertAlmostEqual(a.usage.cost_usd, 0.003 + 0.030, places=6)

    def test_a_missing_usage_block_is_estimated_not_treated_as_zero(self):
        a = _Accountant("claude-sonnet-4-5")
        a._account_response(None, None, "p" * 4000, "r" * 400)
        self.assertTrue(a.usage.tokens_estimated)
        self.assertGreater(a.usage.input_tokens, 900)
        self.assertGreater(a.usage.cost_usd, 0.0,
                           "a request was issued; $0.000 is a false claim")

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
        self.assertEqual(a.usage.input_tokens + a.usage.output_tokens, 2000,
                         "unknown price is not the same as unknown usage")

    def test_stating_a_price_restores_the_dollar_cap_for_that_model(self):
        os.environ["JITTEST_MODEL_PRICE"] = "1.00,3.00"
        a = _Accountant("z-ai/glm-5.2")
        a._account_response(1_000_000, 1_000_000, "p", "r")
        self.assertTrue(a.usage.priced)
        self.assertAlmostEqual(a.usage.cost_usd, 4.00, places=6)


class WhatTheReportSays(unittest.TestCase):
    def _report(self, **kw):
        base = dict(repo=".", base="a", head="b", model="m")
        base.update(kw)
        return Report(**base)

    def test_a_measured_priced_run_shows_a_plain_figure(self):
        r = self._report(cost_usd=0.123, priced=True)
        self.assertEqual(r.cost_line, "$0.123")

    def test_an_estimated_run_is_marked_as_such(self):
        r = self._report(cost_usd=0.123, priced=True, tokens_estimated=True)
        self.assertIn("~", r.cost_line)
        self.assertIn("estimated", r.cost_line)

    def test_an_unpriced_run_reports_tokens_instead_of_a_false_zero(self):
        r = self._report(priced=False, input_tokens=1200, output_tokens=800)
        self.assertIn("unpriced", r.cost_line)
        self.assertIn("2,000", r.cost_line)

    def test_an_unpriced_run_with_no_tokens_says_only_unpriced(self):
        r = self._report(priced=False)
        self.assertEqual(r.cost_line, "unpriced")

    def test_the_json_carries_the_caveat_not_just_the_number(self):
        """The eval harness reads JSON. A bare cost_usd of 0.0 from an unpriced
        model would be averaged into mean_cost_usd as if it were free."""
        r = self._report(priced=False, input_tokens=10, output_tokens=5)
        payload = r.as_dict()
        self.assertIn("priced", payload)
        self.assertFalse(payload["priced"])
        self.assertEqual(payload["input_tokens"], 10)
        self.assertEqual(payload["output_tokens"], 5)
        self.assertIn("tokens_estimated", payload)


if __name__ == "__main__":
    unittest.main()
