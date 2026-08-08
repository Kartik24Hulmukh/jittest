"""End-to-end zero-spend and fake transport test suite for Phase C frozen transport (Stage 3)."""

import json
import os
import unittest
import urllib.error
from unittest import mock

from jittest.budget import BudgetManager
from jittest.llm import HTTPLLM, LLMError, RateLimitedError, TimedOutError


class ZeroSpendTransportTests(unittest.TestCase):
    def test_zero_spend_ceiling_blocks_network_dispatch(self):
        """At USD 0.00 ceiling, zero network dispatches or HTTP calls can occur."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
        llm = HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True)

        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(LLMError):
                llm.complete("system", "user")
            mock_urlopen.assert_not_called()

    def test_frozen_mode_rejects_banned_env_vars(self):
        """Phase C frozen mode must raise ValueError if environment overrides are present."""
        bm = BudgetManager(authorized_spend_ceiling_usd=1.00)
        for env_var in ("JITTEST_API_BASE", "JITTEST_MODEL", "JITTEST_BUDGET_USD", "JITTEST_MAX_RETRIES"):
            with (
                mock.patch.dict(os.environ, {env_var: "override_value"}),
                self.assertRaises(ValueError),
            ):
                HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True)

    def test_non_mistral_model_rejected_in_phase_c(self):
        """Phase C mode must reject non-Mistral models (Anthropic, OpenAI, arbitrary)."""
        bm = BudgetManager(authorized_spend_ceiling_usd=1.00)
        for bad_model in ("anthropic/claude-sonnet-4-5", "openai/gpt-4o", "arbitrary/model"):
            with self.assertRaises(ValueError):
                HTTPLLM(bad_model, budget_manager=bm, api_key="fake-key", phase_c=True)

    def test_frozen_mode_rejects_unknown_kwargs(self):
        """Phase C frozen mode must reject unknown keyword arguments."""
        bm = BudgetManager(authorized_spend_ceiling_usd=1.00)
        with self.assertRaises(TypeError):
            HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True, unknown_arg=123)

    def test_frozen_mode_requires_explicit_budget_manager(self):
        """Phase C frozen mode must require explicit BudgetManager dependency injection."""
        with self.assertRaises(ValueError):
            HTTPLLM("mistral/codestral-2508", api_key="fake-key", phase_c=True)

    def test_frozen_mode_rejects_temperature_override(self):
        """Temperature override != 0.0 must be rejected in Phase C mode."""
        bm = BudgetManager(authorized_spend_ceiling_usd=1.00)
        with self.assertRaises(ValueError):
            HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", temperature=0.7, phase_c=True)


class FakeTransportPathTests(unittest.TestCase):
    def setUp(self):
        self.bm = BudgetManager(authorized_spend_ceiling_usd=10.00)
        self.llm = HTTPLLM("mistral/codestral-2508", budget_manager=self.bm, api_key="fake-key", phase_c=True)

    def test_fake_transport_200_success(self):
        """Fake transport returning 200 OK completes cleanly and reconciles actual usage."""
        fake_response = mock.MagicMock()
        fake_response.read.return_value = json.dumps(
            {
                "choices": [{"message": {"content": "response content"}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        ).encode("utf-8")
        fake_response.__enter__.return_value = fake_response

        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            res = self.llm.complete("sys", "usr")
            self.assertEqual(len(res), 1)
            self.assertEqual(self.bm.executed_requests, 1)

    def test_fake_transport_missing_usage_marks_unverified(self):
        """Missing usage in response must mark usage unverified in Phase C mode."""
        fake_response = mock.MagicMock()
        fake_response.read.return_value = json.dumps(
            {"choices": [{"message": {"content": "no usage"}}]}
        ).encode("utf-8")
        fake_response.__enter__.return_value = fake_response

        with mock.patch("urllib.request.urlopen", return_value=fake_response):
            self.llm.complete("sys", "usr")
            self.assertTrue(getattr(self.llm.usage, "unverified", False))

    def test_fake_transport_429_rate_limited_exhaustion(self):
        """HTTP 429 response on all retries raises RateLimitedError."""
        err = urllib.error.HTTPError(
            url="https://api.mistral.ai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs={},
            fp=mock.MagicMock(read=mock.MagicMock(return_value=b"rate limit")),
        )
        with (
            mock.patch("urllib.request.urlopen", side_effect=err),
            mock.patch.object(self.llm, "_sleep"),
            self.assertRaises(RateLimitedError),
        ):
            self.llm.complete("sys", "usr")

    def test_fake_transport_timeout_exhaustion(self):
        """Timeout on all retries raises TimedOutError."""
        with (
            mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
            mock.patch.object(self.llm, "_sleep"),
            self.assertRaises(TimedOutError),
        ):
            self.llm.complete("sys", "usr")

    def test_fake_transport_connection_error(self):
        """ConnectionError on all retries raises LLMError."""
        with (
            mock.patch("urllib.request.urlopen", side_effect=ConnectionError("disconnected")),
            mock.patch.object(self.llm, "_sleep"),
            self.assertRaises(LLMError),
        ):
            self.llm.complete("sys", "usr")

    def test_fake_transport_malformed_json_response(self):
        """Malformed JSON response from server raises LLMError."""
        fake_response = mock.MagicMock()
        fake_response.read.return_value = b"not valid json"
        fake_response.__enter__.return_value = fake_response

        with (
            mock.patch("urllib.request.urlopen", return_value=fake_response),
            self.assertRaises(LLMError),
        ):
            self.llm.complete("sys", "usr")


if __name__ == "__main__":
    unittest.main()
