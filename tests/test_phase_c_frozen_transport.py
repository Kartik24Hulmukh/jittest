"""End-to-end zero-spend and fake transport test suite for Phase C frozen transport (Stage 3)."""

import json
import os
import unittest
from unittest import mock

from jittest.budget import BudgetManager
from jittest.llm import HTTPLLM, LLMError


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
        with (
            mock.patch.dict(os.environ, {"JITTEST_API_BASE": "https://attacker.com/v1"}),
            self.assertRaises(ValueError),
        ):
            HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True)

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


if __name__ == "__main__":
    unittest.main()
