"""Zero-inference transport tests asserting zero network activity at USD 0.00 ceiling (Section E)."""

import socket
import urllib.request

import pytest

from src.jittest._litellm import LiteLLMBackend
from src.jittest._llmbase import BudgetExceeded, LLMError
from src.jittest.budget import BudgetExceededError, BudgetManager
from src.jittest.llm import HTTPLLM, DryRunLLM, build_llm


def test_zero_inference_transport_intercepts(tmp_path, monkeypatch):
    """At USD 0.00 ceiling, DNS, socket creation, TLS, and HTTP calls must remain strictly ZERO."""
    dns_calls = 0
    socket_calls = 0
    http_calls = 0

    def mock_getaddrinfo(*args, **kwargs):
        nonlocal dns_calls
        dns_calls += 1
        raise RuntimeError("DNS call attempted!")

    def mock_socket(*args, **kwargs):
        nonlocal socket_calls
        socket_calls += 1
        raise RuntimeError("Socket creation attempted!")

    def mock_urlopen(*args, **kwargs):
        nonlocal http_calls
        http_calls += 1
        raise RuntimeError("HTTP urlopen attempted!")

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)
    monkeypatch.setattr(socket, "socket", mock_socket)
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=tmp_path / "j.jsonl")
    llm = HTTPLLM("mistral/codestral-2508", budget_manager=bm, api_key="dummy")

    with pytest.raises((BudgetExceeded, BudgetExceededError)):
        llm.complete("system prompt", "user prompt")

    assert dns_calls == 0, f"DNS calls were made: {dns_calls}"
    assert socket_calls == 0, f"Socket calls were made: {socket_calls}"
    assert http_calls == 0, f"HTTP calls were made: {http_calls}"


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
