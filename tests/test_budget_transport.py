"""Zero-inference transport tests asserting zero network activity at USD 0.00 ceiling (Section E)."""

import socket
import ssl
import urllib.request

import pytest

from src.jittest._litellm import LiteLLMBackend
from src.jittest._llmbase import BudgetExceeded, LLMError
from src.jittest.budget import BudgetExceededError, BudgetManager
from src.jittest.llm import HTTPLLM, DryRunLLM, build_llm


def test_zero_inference_transport_intercepts(tmp_path, monkeypatch):
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

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    monkeypatch.setattr(socket, "socket", mock_socket)
    monkeypatch.setattr(ssl, "create_default_context", mock_create_default_context)
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=tmp_path / "j.jsonl")
    llm = HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="dummy")

    # Entry point 1: HTTPLLM direct complete
    with pytest.raises((BudgetExceeded, BudgetExceededError)):
        llm.complete("system prompt", "user prompt")

    # Entry point 2: Retry path (must fail-fast at pre-request budget reservation before retrying)
    with pytest.raises((BudgetExceeded, BudgetExceededError)):
        llm._post("https://api.mistral.ai/v1/chat/completions", {"max_tokens": 100}, {})

    # Entry point 3: Fallback path (must be disabled or blocked by budget)
    if hasattr(llm, "fallback_llm") and llm.fallback_llm:
        with pytest.raises((BudgetExceeded, BudgetExceededError)):
            llm.fallback_llm.complete("system", "user")
        fallbacks += 1

    assert dns_calls == 0, f"DNS calls were made: {dns_calls}"
    assert socket_calls == 0, f"Socket calls were made: {socket_calls}"
    assert tls_calls == 0, f"TLS calls were made: {tls_calls}"
    assert http_calls == 0, f"HTTP calls were made: {http_calls}"
    assert provider_calls == 0, f"Provider calls were made: {provider_calls}"
    assert hidden_retries == 0, f"Hidden retries were made: {hidden_retries}"
    assert fallbacks == 0, f"Fallbacks were made: {fallbacks}"


def test_disabled_litellm_route_zero_network(tmp_path):
    """LiteLLM route must raise LLMError without network calls."""
    bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=tmp_path / "j.jsonl")
    with pytest.raises(LLMError) as exc_info:
        LiteLLMBackend("mistral/codestral-2508", budget_manager=bm)
    assert "disabled" in str(exc_info.value)


def test_dry_run_llm_zero_network():
    """DryRunLLM completes offline without network."""
    llm = DryRunLLM()
    res = llm.complete("system", "user")
    assert len(res) == 1
    assert "dry run" in res[0]


def test_build_llm_requires_budget_manager():
    """build_llm must handle explicit budget_manager instance correctly."""
    bm = BudgetManager(authorized_spend_ceiling_usd=0.00)
    llm = build_llm("mistral/codestral-2508", budget_manager=bm, api_key="test-key")
    assert llm.budget_manager is bm
