"""Tests for transport retry behavior in HTTPLLM."""
from __future__ import annotations

import http.client
import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from jittest.llm import HTTPLLM, LLMError


class TestTransportRetry(unittest.TestCase):
    """Test retry behavior when encountering transport errors like RemoteDisconnected."""

    def test_remote_disconnected_retry_success(self):
        """RemoteDisconnected on attempt 1 followed by success returns body and transport_retries == 1."""
        llm = HTTPLLM(model="openai/gpt-4o", api_key="test-key")

        resp_data = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        attempts: list[object] = [
            http.client.RemoteDisconnected("Remote end closed connection without response"),
            mock_resp,
        ]

        def fake_urlopen(req, timeout=None):
            val = attempts.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch.object(llm, "_sleep", side_effect=sleep_calls.append):
            result = llm.complete(system="sys", user="user")

        self.assertEqual(result, ["ok"])
        self.assertEqual(llm.transport_retries, 1)
        self.assertTrue(len(sleep_calls) > 0)

    def test_remote_disconnected_every_attempt_raises_llm_error(self):
        """RemoteDisconnected on every attempt raises LLMError and transport_retries == max_attempts - 1."""
        llm = HTTPLLM(model="openai/gpt-4o", api_key="test-key")

        def fake_urlopen(req, timeout=None):
            raise http.client.RemoteDisconnected("Remote end closed connection without response")

        sleep_calls: list[float] = []

        with (
            patch("urllib.request.urlopen", side_effect=fake_urlopen),
            patch.object(llm, "_sleep", side_effect=sleep_calls.append),
            self.assertRaises(LLMError) as cm,
        ):
            llm.complete(system="sys", user="user")

        self.assertFalse(isinstance(cm.exception, http.client.RemoteDisconnected))
        self.assertIn("model request failed after retries", str(cm.exception))
        self.assertEqual(llm.transport_retries, llm.max_attempts - 1)
        self.assertTrue(len(sleep_calls) > 0)

    def test_non_retryable_http_error_401_raises_immediately(self):
        """Non-retryable HTTPError (401) raises immediately and does NOT increment transport_retries."""
        llm = HTTPLLM(model="openai/gpt-4o", api_key="test-key")

        err_fp = io.BytesIO(b"Unauthorized")
        http_err = urllib.error.HTTPError(
            url="http://fake", code=401, msg="Unauthorized", hdrs={}, fp=err_fp
        )

        sleep_calls: list[float] = []

        with (
            patch("urllib.request.urlopen", side_effect=http_err),
            patch.object(llm, "_sleep", side_effect=sleep_calls.append),
            self.assertRaises(LLMError) as cm,
        ):
            llm.complete(system="sys", user="user")

        self.assertIn("HTTP 401", str(cm.exception))
        self.assertEqual(llm.transport_retries, 0)
        self.assertEqual(len(sleep_calls), 0)

    def test_connection_reset_error_bare_retried(self):
        """ConnectionResetError raised bare is also retried."""
        llm = HTTPLLM(model="openai/gpt-4o", api_key="test-key")

        resp_data = json.dumps({"choices": [{"message": {"content": "reset_ok"}}]}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = resp_data
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False

        attempts: list[object] = [ConnectionResetError("Connection reset by peer"), mock_resp]

        def fake_urlopen(req, timeout=None):
            val = attempts.pop(0)
            if isinstance(val, Exception):
                raise val
            return val

        sleep_calls: list[float] = []

        with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             patch.object(llm, "_sleep", side_effect=sleep_calls.append):
            result = llm.complete(system="sys", user="user")

        self.assertEqual(result, ["reset_ok"])
        self.assertEqual(llm.transport_retries, 1)
        self.assertTrue(len(sleep_calls) > 0)


if __name__ == "__main__":
    unittest.main()
