"""Unit tests for jittest.llm.melious_router (offline, MockTransport).

Every test injects a deterministic HTTP transport so failover, cooldown, and
deadline behaviour is exercised WITHOUT network access. Live-network stress is
a separate script (scripts/ga73_live_stress.py) that requires MELIOUS_API_KEY.
"""

from __future__ import annotations

import json
import unittest

try:
    import httpx  # noqa: F401
except ImportError:
    httpx = None  # type: ignore[assignment]
    raise unittest.SkipTest("httpx not installed; install jittest[melious] to run router tests") from None


import httpx

from jittest.llm.melious_router import (
    AuthenticationError,
    ChainExhaustedError,
    DeadlineExceeded,
    MeliousRouter,
    ModelUnavailableError,
    _validate_base,
)
from jittest.llm.melious_router import (
    TransportError as MeliousTransportError,
)


def _fake_response(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://test/chat/completions"))


CHAT_OK = {"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}], "usage": {"total_tokens": 5}}
CHAT_LEN = {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}], "usage": {"total_tokens": 3}}


def _router(handler) -> MeliousRouter:
    return MeliousRouter(api_key="k", transport=httpx.MockTransport(handler))


class ValidateBaseTests(unittest.TestCase):
    def test_http_rejected(self):
        with self.assertRaises(ValueError):
            _validate_base("http://api.melious.ai/v1")

    def test_credentials_rejected(self):
        with self.assertRaises(ValueError):
            _validate_base("https://user:pass@api.melious.ai/v1")

    def test_https_ok(self):
        self.assertEqual(_validate_base("https://api.melious.ai/v1"), "https://api.melious.ai/v1")

    def test_bare_host_gains_https(self):
        self.assertEqual(_validate_base("api.melious.ai/v1"), "https://api.melious.ai/v1")


class RouterAuthTests(unittest.TestCase):
    def test_missing_key_is_rejected_before_network(self):
        r = MeliousRouter(api_key="")
        try:
            with self.assertRaises(AuthenticationError):
                r.list_models()
            with self.assertRaises(AuthenticationError):
                r.complete("glm-5.3", "hi")
        finally:
            r.close()

    def test_401_raises_authentication_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "catalogue authorization rejected"}, request=request)

        r = _router(handler)
        try:
            with self.assertRaises(AuthenticationError):
                r.complete("glm-5.3", "hi")
        finally:
            r.close()


class RouterFailoverTests(unittest.TestCase):
    def test_404_fails_over_to_chain(self):
        calls: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            model = body["model"]
            calls.append((model, request.url.path))
            if model == "glm-4.5":
                return httpx.Response(404, json={"error": "not found"}, request=request)
            return httpx.Response(200, json=CHAT_OK, request=request)

        r = _router(handler)
        try:
            out = r.complete("glm-4.5", "hi")
        finally:
            r.close()
        self.assertEqual(out.model, "glm-5.3")
        self.assertEqual([m for m, _ in calls], ["glm-4.5", "glm-5.3"])

    def test_chain_exhausted_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"}, request=request)

        r = _router(handler)
        try:
            with self.assertRaises(ChainExhaustedError):
                r.complete("glm-4.5", "hi")
        finally:
            r.close()


class Router429Tests(unittest.TestCase):
    def test_429_retries_with_bounded_cooldown(self):
        seq = [429, 429, 200]

        def handler(request: httpx.Request) -> httpx.Response:
            code = seq.pop(0)
            if code == 429:
                return httpx.Response(429, json={"error": "rate limited"}, request=request)
            return httpx.Response(200, json=CHAT_OK, request=request)

        r = _router(handler)
        try:
            out = r.complete("glm-5.3", "hi")
        finally:
            r.close()
        self.assertEqual(out.attempts, 3)

    def test_429_with_tiny_deadline_raises_deadline_exceeded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "rate limited"}, request=request)

        r = _router(handler)
        try:
            with self.assertRaises(DeadlineExceeded):
                r.complete("glm-5.3", "hi", deadline=0.001)
        finally:
            r.close()


class RouterTruncationTests(unittest.TestCase):
    def test_length_finish_escalates_max_tokens(self):
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body["max_tokens"])
            if len(calls) == 1:
                return httpx.Response(200, json=CHAT_LEN, request=request)
            return httpx.Response(200, json=CHAT_OK, request=request)

        r = _router(handler)
        try:
            out = r.complete("glm-5.3", "hi", max_tokens=256)
        finally:
            r.close()
        self.assertEqual(calls, [256, 1024])
        self.assertEqual(out.finish_reason, "stop")

    def test_length_finish_deadline_bounded(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=CHAT_LEN, request=request)

        r = _router(handler)
        try:
            with self.assertRaises(DeadlineExceeded):
                r.complete("glm-5.3", "hi", deadline=0.01, max_tokens=256)
        finally:
            r.close()


class RouterModelUnavailableTests(unittest.TestCase):
    def test_absent_model_raises_model_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "absent"}, request=request)

        r = _router(handler)
        try:
            with self.assertRaises(ModelUnavailableError):
                r.complete("nonexistent-model", "hi")
        finally:
            r.close()

    def test_catalogue_lists_models(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "glm-5.3"}, {"id": "kimi-k3"}]}, request=request)

        r = _router(handler)
        try:
            models = r.list_models()
        finally:
            r.close()
        self.assertEqual(models, ["glm-5.3", "kimi-k3"])


if __name__ == "__main__":
    unittest.main()

class RouterTransportTests(unittest.TestCase):
    def test_transport_error_becomes_transport_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated dropped network")

        r = _router(handler)
        try:
            with self.assertRaises(MeliousTransportError):
                r.complete("glm-5.3", "hi")
        finally:
            r.close()

    def test_transport_error_fails_over(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            calls.append(body["model"])
            if body["model"] == "glm-4.5":
                raise httpx.ReadTimeout("simulated dropped network")
            return httpx.Response(200, json=CHAT_OK, request=request)

        r = _router(handler)
        try:
            out = r.complete("glm-4.5", "hi")
        finally:
            r.close()
        self.assertEqual(out.model, "glm-5.3")
        self.assertEqual(calls, ["glm-4.5", "glm-5.3"])


class RouterBurstTests(unittest.TestCase):
    def test_ten_parallel_no_uncaught_transport_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=CHAT_OK, request=request)

        import concurrent.futures

        r = _router(handler)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                results = list(
                    pool.map(
                        lambda _m: r.complete("glm-5.3", "hi", deadline=5.0, max_tokens=64),
                        range(10),
                    )
                )
        finally:
            r.close()
        self.assertEqual(len(results), 10)
        self.assertTrue(all(o.finish_reason == "stop" for o in results))