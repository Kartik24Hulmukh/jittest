"""Deterministic scheduler tests; live four-model load evidence is separate."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

try:
    import httpx
except ImportError:
    raise unittest.SkipTest("requires jittest[melious]") from None

from jittest.melious import (
    DEFAULT_MAX_INFLIGHT_PER_MODEL,
    DeadlineExceeded,
    MeliousRouter,
)


class BackpressureContract(unittest.TestCase):
    def test_default_per_model_limit_is_four(self):
        self.assertEqual(DEFAULT_MAX_INFLIGHT_PER_MODEL, 4)
        with MeliousRouter(api_key="test") as router:
            self.assertEqual(router.max_inflight_per_model, 4)

    def test_queue_is_bounded_and_timeout_does_not_dispatch(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def handler(request):
            calls.append(request)
            entered.set()
            self.assertTrue(release.wait(5))
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

        with MeliousRouter(api_key="test", max_inflight_per_model=1,
                           transport=httpx.MockTransport(handler)) as router:
            with ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(router.complete, "glm-5.3", "hi", deadline=10)
                try:
                    self.assertTrue(entered.wait(5))
                    with self.assertRaises(DeadlineExceeded):
                        router.complete("glm-5.3", "queued", deadline=0.01)
                    self.assertEqual(len(calls), 1)
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=5).text, "ok")
            self.assertEqual(router.complete("glm-5.3", "after").text, "ok")

    def test_error_releases_slot(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(401 if len(calls) == 1 else 200, json={
                "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

        from jittest.melious import AuthenticationError
        with MeliousRouter(api_key="test", max_inflight_per_model=1,
                           transport=httpx.MockTransport(handler)) as router:
            with self.assertRaises(AuthenticationError):
                router.complete("glm-5.3", "first")
            self.assertEqual(router.complete("glm-5.3", "second").text, "ok")
            self.assertEqual(len(router._model_slots), 0)

    def test_invalid_inputs_refuse_before_network(self):
        with MeliousRouter(api_key="test") as router:
            for model, prompt, deadline in (
                (None, "hi", 1), ("glm-5.3", {}, 1),
                ("glm-5.3", "hi", True), ("glm-5.3", "hi", "bad"),
            ):
                with self.subTest(model=model, prompt=prompt, deadline=deadline), \
                        self.assertRaises((ValueError, DeadlineExceeded)):
                    router.complete(model, prompt, deadline=deadline)
            self.assertIsNone(router._client)