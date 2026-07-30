"""Cost must be measurable even on an unpriced endpoint (roadmap P-4).

Gate 1 requires a verified catching test "under 1 dollar each". The
evaluation model on its free endpoint is unpriced, so the budget system
degraded to a request-count ceiling and cost per pull request was
unmeasurable: every run emitted "pricing is unknown" and priced=False.

Three changes close that without guessing a price:

  * an operator who knows what their endpoint charges sets
    JITTEST_PRICE_INPUT_PER_MTOK / JITTEST_PRICE_OUTPUT_PER_MTOK, and the run
    computes a real dollar figure with the dollar cap active instead of the
    request-count ceiling;
  * the Report now carries input_tokens and output_tokens behind cost_usd, so
    any cost claim is auditable from the artifact, and the eval summary
    reports mean token counts;
  * a user-priced model at exactly (0, 0) - the free endpoint - gets BOTH the
    dollar cap and the request ceiling, because a zero price makes the cap
    vacuous and the ceiling is the only thing that stops a runaway loop.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from jittest.llm import HTTPLLM, BudgetExceeded
from jittest.pipeline import Report


def _http(model: str = "z-ai/glm-5.2") -> HTTPLLM:
    with mock.patch.dict(os.environ, {"JITTEST_API_KEY": "k"}):
        return HTTPLLM(model, api_key="k")


class UserSuppliedPrice(unittest.TestCase):
    def test_env_price_makes_an_unknown_model_priced(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "0.50",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "2.00"}):
            llm = _http()
            self.assertEqual(llm._price(), (0.50, 2.00))
            self.assertFalse(llm._unpriced)

    def test_token_accounting_uses_the_user_price(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "1.00",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "4.00"}):
            llm = _http()
            llm._account(1_000_000, 250_000)
            self.assertAlmostEqual(llm.usage.cost_usd, 2.00)
            self.assertTrue(llm.usage.priced)
            self.assertEqual(llm.usage.input_tokens, 1_000_000)
            self.assertEqual(llm.usage.output_tokens, 250_000)

    def test_missing_or_malformed_env_price_stays_unpriced(self) -> None:
        with mock.patch.dict(os.environ, {"JITTEST_API_KEY": "k"}, clear=False):
            os.environ.pop("JITTEST_PRICE_INPUT_PER_MTOK", None)
            os.environ.pop("JITTEST_PRICE_OUTPUT_PER_MTOK", None)
            llm = _http()
            self.assertIsNone(llm._price())
            self.assertTrue(llm._unpriced)
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "lots",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "2.0"}):
            self.assertIsNone(_http()._price())

    def test_a_negative_price_is_rejected_not_clamped(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "-1.0",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "2.0"}):
            self.assertIsNone(_http()._price())

    def test_the_builtin_table_still_wins_for_known_models(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "99.0",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "99.0"}):
            llm = HTTPLLM("claude-sonnet-4-5", api_key="k")
            self.assertEqual(llm._price(), (3.00, 15.00))


class FreeEndpointKeepsACeiling(unittest.TestCase):
    """A zero user price satisfies the dollar cap trivially, so the request
    ceiling must still fire - otherwise a free endpoint runs forever."""

    def test_zero_price_still_enforces_the_request_ceiling(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "0",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "0",
                "JITTEST_MAX_TARGETS": "1",
                "JITTEST_CANDIDATES": "1"}):
            llm = _http()
            llm.usage.calls = 6  # ceiling is 1*1 + 5 = 6
            with self.assertRaises(BudgetExceeded):
                llm.complete("s", "u")

    def test_priced_model_uses_the_dollar_cap_not_the_ceiling(self) -> None:
        with mock.patch.dict(os.environ, {
                "JITTEST_API_KEY": "k",
                "JITTEST_PRICE_INPUT_PER_MTOK": "1.00",
                "JITTEST_PRICE_OUTPUT_PER_MTOK": "1.00",
                "JITTEST_MAX_TARGETS": "1",
                "JITTEST_CANDIDATES": "1"}):
            llm = HTTPLLM("z-ai/glm-5.2", api_key="k", budget_usd=0.01)
            llm.usage.cost_usd = 0.02
            llm.usage.calls = 1
            with self.assertRaises(BudgetExceeded):
                llm.complete("s", "u")


class ReportCarriesTheTokens(unittest.TestCase):
    def test_report_token_fields_default_and_serialise(self) -> None:
        report = Report(repo="r", base="b", head="h", model="m")
        self.assertEqual(report.input_tokens, 0)
        self.assertEqual(report.output_tokens, 0)
        d = report.as_dict()
        self.assertIn("input_tokens", d)
        self.assertIn("output_tokens", d)

    def test_token_fields_round_trip(self) -> None:
        report = Report(repo="r", base="b", head="h", model="m",
                        input_tokens=1234, output_tokens=56)
        d = report.as_dict()
        self.assertEqual(d["input_tokens"], 1234)
        self.assertEqual(d["output_tokens"], 56)


if __name__ == "__main__":
    unittest.main()
