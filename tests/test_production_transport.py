"""Production regressions discovered during the continued GA-73 audit."""
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

try:
    import httpx
    import pytest
except ImportError:
    raise unittest.SkipTest("production transport tests require pytest and the melious extra") from None

from jittest.llm import HTTPLLM, LLMError
from jittest.melious import MeliousError, MeliousRouter


@pytest.mark.parametrize("status,body", [(402, {}), (429, {"error": {"code": "insufficient_quota"}})])
def test_router_billing_is_terminal(status, body):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=body)
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router, pytest.raises(MeliousError, match="billing"):
        router.complete("glm-4.5", "hi", deadline=0.02)
    assert len(calls) == 1


@pytest.mark.parametrize("status", [403, 410])
def test_router_retired_leg_fails_over(status):
    calls = []
    def handler(request):
        model = json.loads(request.content)["model"]
        calls.append(model)
        return httpx.Response(status if len(calls) == 1 else 200,
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router:
        assert router.complete("glm-4.5", "hi").model == "glm-5.3"
    assert len(calls) == 2


def test_request_timeout_is_capped_by_remaining_deadline():
    observed = []
    def handler(request):
        observed.append(request.extensions["timeout"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router:
        router.complete("glm-5.3", "hi", deadline=0.25)
    assert all(0 < value <= 0.25 for value in observed[0].values())


@pytest.mark.parametrize("tokens", [0, -1, 65537])
def test_override_tokens_validated(tokens):
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as router, pytest.raises(ValueError):
        router.complete("glm-5.3", "hi", max_tokens=tokens)


def test_direct_base_sends_bare_model(monkeypatch):
    monkeypatch.setenv("JITTEST_API_BASE", "https://api.melious.ai/v1")
    llm = HTTPLLM("melious/glm-5.3", api_key="test")
    assert llm.api_model == "glm-5.3"


def test_gateway_keeps_namespace(monkeypatch):
    monkeypatch.setenv("JITTEST_API_BASE", "https://gateway.example/v1")
    assert HTTPLLM("melious/glm-5.3", api_key="test").api_model == "melious/glm-5.3"


def test_http_quota_is_terminal():
    exc = urllib.error.HTTPError("https://example.test", 429, "quota", {},
        io.BytesIO(b'{"error":{"code":"insufficient_quota"}}'))
    llm = HTTPLLM("melious/glm-5.3", api_key="test")
    with patch("urllib.request.urlopen", side_effect=exc) as post, patch.object(llm, "_sleep") as sleep, pytest.raises(LLMError, match="billing"):
        llm._post("https://example.test", {}, {})
    assert post.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("fx", ["nan", "inf", "-1", "0", "invalid"])
def test_invalid_fx_is_unpriced(monkeypatch, fx):
    from jittest._pricing import price_for
    monkeypatch.delenv("JITTEST_MODEL_PRICE", raising=False)
    monkeypatch.setenv("JITTEST_EUR_USD", fx)
    assert price_for("melious/glm-5.3") is None


def test_pricing_specific_model_and_provider(monkeypatch):
    from jittest._pricing import price_for
    monkeypatch.delenv("JITTEST_MODEL_PRICE", raising=False)
    monkeypatch.setenv("JITTEST_EUR_USD", "1.1355")
    assert price_for("melious/glm-5.3-flash") == pytest.approx((0.11355, 0.4542))
    assert price_for("melious/qwen3.8-27b") == pytest.approx((0.4542, 2.7252))
    assert price_for("other/glm-5.3") is None


def test_retry_connect_error_is_bounded():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            raise httpx.ConnectError("temporary DNS error")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router:
        assert router.complete("glm-5.3", "hi", deadline=2).attempts == 3
    assert len(calls) == 3


def test_escalation_accounts_all_billed_attempts():
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"},
            "finish_reason": "length" if len(calls) == 1 else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}})
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router:
        out = router.complete("glm-5.3", "hi", max_tokens=64)
    assert out.usage == {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}


@pytest.mark.parametrize("error,status", [("model", "model_unavailable"), ("quota", "quota_exhausted")])
def test_pipeline_permanent_refusal_stops_all_generation(error, status):
    from jittest.config import Config
    from jittest.llm import DryRunLLM, ModelUnavailableError, QuotaExhaustedError
    from jittest.pipeline import run

    from .helpers import FixtureRepo
    llm = DryRunLLM()
    exception = ModelUnavailableError("HTTP 410") if error == "model" else QuotaExhaustedError("billing")
    with FixtureRepo() as repo, patch.object(llm, "complete", side_effect=exception) as complete:
        report = run(repo.path, repo.base, repo.head,
            Config(risk_threshold=0, candidates_per_target=4, max_targets=3, sandbox_mode="off"), llm)
    assert complete.call_count == 1
    assert report.diff_status == status
    assert report.discarded[status] == 1


def test_transport_retries_do_not_exhaust_truncation_escalation():
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("temporary DNS error")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"},
            "finish_reason": "length" if len(calls) == 2 else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}})
    with MeliousRouter(api_key="test", transport=httpx.MockTransport(handler)) as router:
        assert router.complete("glm-5.3", "hi", deadline=3, max_tokens=64).attempts == 3


def test_required_sandbox_never_spends_when_unavailable():
    from jittest.config import Config
    from jittest.llm import DryRunLLM
    from jittest.pipeline import run
    from jittest.sandbox import SandboxUnavailable

    from .helpers import FixtureRepo
    llm = DryRunLLM()
    with FixtureRepo() as repo, patch("jittest.pipeline.sandbox_plan", side_effect=SandboxUnavailable("required sandbox unavailable")), patch.object(llm, "complete") as complete:
        report = run(repo.path, repo.base, repo.head, Config(risk_threshold=0, sandbox_mode="required"), llm)
    complete.assert_not_called()
    assert report.diff_status == "sandbox_unavailable"


@pytest.mark.parametrize("priced", [True, False])
def test_preflight_requires_price_before_network(priced):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("audit_preflight", Path(__file__).parents[1] / "eval/preflight_model.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    llm = HTTPLLM("melious/glm-5.3", api_key="test")
    with patch.object(module, "build_llm", return_value=llm), patch.object(llm, "_price", return_value=(1, 3) if priced else None), patch.object(llm, "complete", return_value=["OK"]) as complete:
        if priced:
            assert module.preflight_model("melious/glm-5.3")["status"] == "responsive"
            complete.assert_called_once()
        else:
            with pytest.raises(LLMError, match="unpriced"):
                module.preflight_model("melious/glm-5.3")
            complete.assert_not_called()



def test_no_response_transport_failure_has_honest_cause():
    from jittest.config import Config
    from jittest.llm import DryRunLLM
    from jittest.pipeline import run

    from .helpers import FixtureRepo
    llm = DryRunLLM()
    with FixtureRepo() as repo, patch.object(llm, "complete", side_effect=LLMError("DNS failed")):
        report = run(repo.path, repo.base, repo.head, Config(risk_threshold=0, candidates_per_target=1, sandbox_mode="off"), llm)
    assert report.diff_status == "model_error"
    assert report.model_requests == 0

@pytest.mark.parametrize('status,body', [(500, {'error': 'down'}), (200, {'choices': 'broken'}), (200, {'choices': [{'message': {'content': None}}]})])
def test_router_malformed_responses_are_typed(status, body):
    with MeliousRouter(api_key='test', transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))) as router, pytest.raises(MeliousError):
        router.complete('glm-5.3', 'hi', deadline=1)


def test_router_concurrent_first_use_has_one_client():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    gate = threading.Barrier(16)
    with MeliousRouter(api_key='test', transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))) as router:
        def get_client(_):
            gate.wait(timeout=5)
            return router._ensure_client()
        with ThreadPoolExecutor(max_workers=16) as pool:
            clients = list(pool.map(get_client, range(16)))
        try:
            assert len({id(c) for c in clients}) == 1
        finally:
            for c in clients:
                c.close()

@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_router_transient_server_failure_is_retried_but_bounded(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status if len(calls) == 1 else 200, json={'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]})
    with MeliousRouter(api_key='test', transport=httpx.MockTransport(handler)) as router:
        result = router.complete('glm-5.3', 'hi', deadline=10)
    assert result.attempts == 2
    assert len(calls) == 2
