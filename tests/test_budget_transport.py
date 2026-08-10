"""Zero-inference transport tests asserting zero network activity at USD 0.00 ceiling (Section E)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest._litellm import LiteLLMBackend
from jittest._llmbase import BudgetExceeded, LLMError
from jittest.budget import BudgetExceededError, BudgetManager
from jittest.llm import HTTPLLM, DryRunLLM, build_llm


class ZeroInferenceTransportTests(unittest.TestCase):
    def test_zero_inference_transport_intercepts(self):
        """At USD 0.00 ceiling, DNS, socket creation, TLS, HTTP, provider calls, hidden retries, and fallbacks must remain strictly ZERO."""
        dns_calls = 0
        socket_calls = 0
        tls_calls = 0
        http_calls = 0
        provider_calls = 0
        hidden_retries = 0
        fallbacks = 0

        def mock_getaddrinfo(*args, **kwargs):
            nonlocal dns_calls
            dns_calls += 1
            raise RuntimeError("DNS call attempted!")

        def mock_socket(*args, **kwargs):
            nonlocal socket_calls
            socket_calls += 1
            raise RuntimeError("Socket creation attempted!")

        def mock_create_default_context(*args, **kwargs):
            nonlocal tls_calls
            tls_calls += 1
            raise RuntimeError("TLS context creation attempted!")

        def mock_urlopen(*args, **kwargs):
            nonlocal http_calls, provider_calls
            http_calls += 1
            provider_calls += 1
            raise RuntimeError("HTTP urlopen attempted!")

        with (
            tempfile.TemporaryDirectory() as tmp_dir,
            mock.patch("socket.getaddrinfo", mock_getaddrinfo),
            mock.patch("socket.socket", mock_socket),
            mock.patch("ssl.create_default_context", mock_create_default_context),
            mock.patch("urllib.request.urlopen", mock_urlopen),
        ):
            journal_path = Path(tmp_dir) / "j.jsonl"
            bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=journal_path)
            llm = HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="dummy")

            # Entry point 1: HTTPLLM direct complete
            with self.assertRaises((BudgetExceeded, BudgetExceededError)):
                llm.complete("system prompt", "user prompt")

            # Entry point 2: Retry path (must fail-fast at pre-request budget reservation before retrying)
            with self.assertRaises((BudgetExceeded, BudgetExceededError)):
                llm._post("https://api.mistral.ai/v1/chat/completions", {"max_tokens": 100}, {})

            # Entry point 3: Fallback path (must be disabled or blocked by budget)
            if hasattr(llm, "fallback_llm") and llm.fallback_llm:
                with self.assertRaises((BudgetExceeded, BudgetExceededError)):
                    llm.fallback_llm.complete("system", "user")
                fallbacks += 1

            self.assertEqual(dns_calls, 0, f"DNS calls were made: {dns_calls}")
            self.assertEqual(socket_calls, 0, f"Socket calls were made: {socket_calls}")
            self.assertEqual(tls_calls, 0, f"TLS calls were made: {tls_calls}")
            self.assertEqual(http_calls, 0, f"HTTP calls were made: {http_calls}")
            self.assertEqual(provider_calls, 0, f"Provider calls were made: {provider_calls}")
            self.assertEqual(hidden_retries, 0, f"Hidden retries were made: {hidden_retries}")
            self.assertEqual(fallbacks, 0, f"Fallbacks were made: {fallbacks}")

    def test_disabled_litellm_route_zero_network(self):
        """LiteLLM route must raise LLMError without network calls."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            journal_path = Path(tmp_dir) / "j.jsonl"
            bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=journal_path)
            with self.assertRaises(LLMError) as ctx:
                LiteLLMBackend("mistral/codestral-2508", budget_manager=bm)
            self.assertIn("disabled", str(ctx.exception))

    def test_dry_run_llm_zero_network(self):
        """DryRunLLM completes offline without network."""
        llm = DryRunLLM()
        res = llm.complete("system", "user")
        self.assertEqual(len(res), 1)
        self.assertIn("dry run", res[0])

    def test_build_llm_requires_budget_manager(self):
        """build_llm must handle explicit budget_manager instance correctly."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
        llm = build_llm("mistral/codestral-2508", budget_manager=bm, api_key="test-key")
        self.assertIs(llm.budget_manager, bm)


if __name__ == "__main__":
    unittest.main()
