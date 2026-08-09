"""Frozen-config tamper rejection and zero-socket verification tests (Mission M3)."""

import os
import unittest
from unittest import mock

from jittest.budget import BudgetManager
from jittest.llm import HTTPLLM, LLMError


class FrozenConfigTamperTests(unittest.TestCase):
    def test_env_tamper_attempts_rejected_in_phase_c(self):
        """Attempts to tamper with model, budget, sandbox, endpoints via env vars fail before dispatch."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
        banned_envs = [
            ("JITTEST_MODEL", "openai/gpt-4o"),
            ("JITTEST_BUDGET_USD", "1000.0"),
            ("JITTEST_API_BASE", "https://attacker.com/v1"),
            ("JITTEST_SANDBOX", "off"),
            ("JITTEST_MAX_RETRIES", "99"),
        ]
        for name, val in banned_envs:
            with (
                mock.patch.dict(os.environ, {name: val}),
                self.assertRaises(ValueError),
            ):
                HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True)

    def test_non_mistral_model_tamper_rejected_in_phase_c(self):
        """Attempts to specify non-Mistral models in Phase C fail before dispatch."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
        bad_models = [
            "anthropic/claude-3-5-sonnet",
            "openai/gpt-4o",
            "google/gemini-pro",
            "custom/local-llm",
        ]
        for model_name in bad_models:
            with self.assertRaises(ValueError):
                HTTPLLM(model_name, budget_manager=bm, api_key="fake-key", phase_c=True)

    def test_zero_dollar_mode_never_opens_socket(self):
        """Zero-dollar budget mode (USD 0.00) never opens a network socket or dispatches HTTP requests."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
        llm = HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="fake-key", phase_c=True)

        with mock.patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertRaises(LLMError):
                llm.complete("system prompt", "user prompt")
            mock_urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
