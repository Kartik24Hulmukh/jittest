"""Rate-limit handling in HTTPLLM._post.

These tests exist because of a measured failure, not a hypothetical one: an
eval run over 10 BugsInPy bugs measured 0 of them, and the cause was a retry
policy that spent about 31 seconds against a 60-second quota window and threw
away the server's own Retry-After header. Every test below fails if that
behaviour returns.

No network and no real sleeping: urlopen is replaced and _sleep is recorded.
"""
from __future__ import annotations

import email.message
import io
import os
import sys
import unittest
import urllib.error
from datetime import UTC, datetime, timedelta
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from jittest.llm import HTTPLLM, LLMError, retry_after_seconds  # noqa: E402


def _http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://example.invalid/v1/chat/completions", code, "boom",
        headers, io.BytesIO(b"{}"),
    )


class _Response:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(**kwargs) -> HTTPLLM:
    with mock.patch.dict(os.environ, {"JITTEST_API_KEY": "test-key"}, clear=False):
        client = HTTPLLM("z-ai/glm-5.2", budget_usd=1.0, **kwargs)
    client.slept = []
    client._sleep = client.slept.append
    return client


class RetryAfterParsing(unittest.TestCase):

    def test_numeric_header_is_read_as_seconds(self):
        self.assertEqual(retry_after_seconds(_http_error(429, "12")), 12.0)

    def test_fractional_header_is_read(self):
        self.assertAlmostEqual(retry_after_seconds(_http_error(429, "0.5")), 0.5)

    def test_http_date_header_is_read_as_a_delay(self):
        when = datetime.now(UTC) + timedelta(seconds=40)
        stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
        seconds = retry_after_seconds(_http_error(429, stamp))
        self.assertIsNotNone(seconds)
        self.assertGreater(seconds, 20.0)
        self.assertLess(seconds, 60.0)

    def test_past_http_date_clamps_to_zero_not_negative(self):
        when = datetime.now(UTC) - timedelta(seconds=90)
        stamp = when.strftime("%a, %d %b %Y %H:%M:%S GMT")
        self.assertEqual(retry_after_seconds(_http_error(429, stamp)), 0.0)

    def test_absent_header_is_none(self):
        self.assertIsNone(retry_after_seconds(_http_error(429)))

    def test_garbage_header_is_none_rather_than_raising(self):
        self.assertIsNone(retry_after_seconds(_http_error(429, "soon-ish")))


class RetryBehaviour(unittest.TestCase):

    def test_a_429_is_retried_and_the_run_survives(self):
        client = _client()
        responses = [_http_error(429, "3"), _Response(b'{"ok": true}')]

        def fake_urlopen(req, timeout=None):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            body = client._post("https://example.invalid", {}, {})
        self.assertEqual(body, {"ok": True})
        self.assertEqual(client.slept, [3.0])

    def test_retry_after_is_honoured_instead_of_the_power_of_two(self):
        client = _client()
        responses = [_http_error(429, "37"), _Response(b"{}")]

        def fake_urlopen(req, timeout=None):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            client._post("https://example.invalid", {}, {})
        self.assertEqual(client.slept, [37.0])

    def test_retry_after_is_capped_by_the_sleep_ceiling(self):
        client = _client()
        client.max_sleep = 20.0
        responses = [_http_error(429, "6000"), _Response(b"{}")]

        def fake_urlopen(req, timeout=None):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            client._post("https://example.invalid", {}, {})
        self.assertEqual(client.slept, [20.0])

    def test_total_patience_exceeds_a_sixty_second_quota_window(self):
        """The defect in one line: the old policy could not outlast one minute."""
        client = _client()

        def always_limited(req, timeout=None):
            raise _http_error(429, "30")

        with (
            mock.patch("jittest.llm.urllib.request.urlopen", always_limited),
            self.assertRaises(LLMError),
        ):
            client._post("https://example.invalid", {}, {})
        self.assertGreaterEqual(sum(client.slept), 60.0)

    def test_exhaustion_names_the_cause_and_the_remedy(self):
        client = _client()

        def always_limited(req, timeout=None):
            raise _http_error(429, "1")

        with (
            mock.patch("jittest.llm.urllib.request.urlopen", always_limited),
            self.assertRaises(LLMError) as ctx,
        ):
            client._post("https://example.invalid", {}, {})
        message = str(ctx.exception)
        self.assertIn("rate limited", message)
        self.assertIn("JITTEST_MIN_REQUEST_INTERVAL", message)
        self.assertEqual(client.rate_limit_waits, client.max_attempts - 1)

    def test_attempt_count_is_configurable(self):
        client = _client()
        client.max_attempts = 3
        calls = []

        def always_limited(req, timeout=None):
            calls.append(1)
            raise _http_error(429, "1")

        with (
            mock.patch("jittest.llm.urllib.request.urlopen", always_limited),
            self.assertRaises(LLMError),
        ):
            client._post("https://example.invalid", {}, {})
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(client.slept), 2)

    def test_a_non_retryable_status_is_raised_immediately(self):
        client = _client()
        calls = []

        def bad_request(req, timeout=None):
            calls.append(1)
            raise _http_error(400)

        with (
            mock.patch("jittest.llm.urllib.request.urlopen", bad_request),
            self.assertRaises(LLMError) as ctx,
        ):
            client._post("https://example.invalid", {}, {})
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertEqual(len(calls), 1)
        self.assertEqual(client.slept, [])

    def test_a_500_is_retried_without_being_called_rate_limiting(self):
        client = _client()
        client.max_attempts = 2

        def server_error(req, timeout=None):
            raise _http_error(500)

        with (
            mock.patch("jittest.llm.urllib.request.urlopen", server_error),
            self.assertRaises(LLMError) as ctx,
        ):
            client._post("https://example.invalid", {}, {})
        self.assertNotIn("rate limited", str(ctx.exception))
        self.assertEqual(client.rate_limit_waits, 0)

    def test_backoff_never_exceeds_the_ceiling(self):
        client = _client()
        client.max_sleep = 12.0
        for attempt in range(10):
            delay = client._backoff(attempt, None, rate_limited=True)
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, 12.0)


class RequestPacing(unittest.TestCase):

    def test_pacing_is_off_by_default(self):
        client = _client()
        responses = [_Response(b"{}"), _Response(b"{}")]

        def fake_urlopen(req, timeout=None):
            return responses.pop(0)

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            client._post("https://example.invalid", {}, {})
            client._post("https://example.invalid", {}, {})
        self.assertEqual(client.slept, [])

    def test_a_minimum_interval_holds_the_second_request_back(self):
        client = _client(min_request_interval=5.0)
        responses = [_Response(b"{}"), _Response(b"{}")]

        def fake_urlopen(req, timeout=None):
            return responses.pop(0)

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            client._post("https://example.invalid", {}, {})
            client._post("https://example.invalid", {}, {})
        self.assertEqual(len(client.slept), 1)
        self.assertGreater(client.slept[0], 0.0)
        self.assertLessEqual(client.slept[0], 5.0)

    def test_the_first_request_is_never_paced(self):
        client = _client(min_request_interval=30.0)

        def fake_urlopen(req, timeout=None):
            return _Response(b"{}")

        with mock.patch("jittest.llm.urllib.request.urlopen", fake_urlopen):
            client._post("https://example.invalid", {}, {})
        self.assertEqual(client.slept, [])


if __name__ == "__main__":
    unittest.main()
