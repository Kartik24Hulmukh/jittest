"""A read timeout is a transport failure, not the end of a run.

`urllib.request.urlopen` raises a bare `TimeoutError` when a read exceeds its
timeout. `TimeoutError` is a sibling of `urllib.error.URLError` under `OSError`,
not a subclass of it, so the retry loop in `_post` never caught one. The first
slow response ended the request outright and the bug it belonged to was
recorded with no cause.

On the first kimi-k3 smoke run that cost 5 of 10 bugs and pulled the completion
rate to 0.30, below the 0.80 evidence floor. Models that always emit a
reasoning trace make slow responses ordinary rather than rare, so this is a
permanent condition to handle and not a one-off.
"""
from __future__ import annotations

import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jittest.llm import HTTPLLM, LLMError  # noqa: E402

_URL = "https://example.invalid/v1/chat/completions"

# Empty strings neutralise anything a developer already exported, so the same
# assertions hold on a laptop mid-debugging and on a clean CI runner.
_BASE_ENV = {
    "JITTEST_API_KEY": "test-key",
    "JITTEST_API_BASE": "",
    "JITTEST_HTTP_TIMEOUT": "",
    "JITTEST_MAX_RETRIES": "",
    "JITTEST_RETRY_MAX_SLEEP": "",
    "JITTEST_MIN_REQUEST_INTERVAL": "",
}


class _Response:
    """The slice of an http response that `_post` actually touches."""

    def __init__(self, payload: dict):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


def _client(env: dict | None = None, **kwargs) -> HTTPLLM:
    environ = dict(_BASE_ENV)
    environ.update(env or {})
    with mock.patch.dict("os.environ", environ):
        client = HTTPLLM("openai/gpt-4o-mini", **kwargs)
    client.slept = []
    client._sleep = client.slept.append
    return client


class TheShapeOfTheBug(unittest.TestCase):
    def test_a_read_timeout_is_not_a_url_error(self):
        """The whole defect in one assertion. If this ever becomes true the
        extra except clause in `_post` is redundant and can go."""
        self.assertFalse(issubclass(TimeoutError, urllib.error.URLError))
        self.assertTrue(issubclass(TimeoutError, OSError))


class ReadTimeouts(unittest.TestCase):
    def test_a_read_timeout_is_retried_rather_than_ending_the_run(self):
        client = _client()
        with mock.patch("jittest.llm.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [
                TimeoutError(), TimeoutError(), _Response({"ok": True}),
            ]
            body = client._post(_URL, {}, {})
        self.assertEqual(body, {"ok": True})
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual(len(client.slept), 2)

    def test_read_timeouts_are_counted(self):
        client = _client()
        with mock.patch("jittest.llm.urllib.request.urlopen") as urlopen:
            urlopen.side_effect = [
                TimeoutError(), TimeoutError(), _Response({"ok": True}),
            ]
            client._post(_URL, {}, {})
        self.assertEqual(client.timeout_retries, 2)

    def test_exhaustion_names_the_cause_and_the_remedy(self):
        client = _client(env={"JITTEST_MAX_RETRIES": "3"})
        with (
            mock.patch("jittest.llm.urllib.request.urlopen") as urlopen,
            self.assertRaises(LLMError) as ctx,
        ):
            urlopen.side_effect = TimeoutError()
            client._post(_URL, {}, {})
        message = str(ctx.exception)
        self.assertIn("JITTEST_HTTP_TIMEOUT", message)
        self.assertIn("3 attempts", message)
        self.assertIn("3 read timeouts", message)

    def test_a_timeout_does_not_report_itself_as_rate_limiting(self):
        """Two different causes must stay distinguishable in the error text,
        or the disposition table records the wrong remedy."""
        client = _client(env={"JITTEST_MAX_RETRIES": "2"})
        with (
            mock.patch("jittest.llm.urllib.request.urlopen") as urlopen,
            self.assertRaises(LLMError) as ctx,
        ):
            urlopen.side_effect = TimeoutError()
            client._post(_URL, {}, {})
        self.assertNotIn("rate limited", str(ctx.exception))


class TimeoutConfiguration(unittest.TestCase):
    def test_the_default_is_generous_enough_for_a_reasoning_model(self):
        self.assertGreaterEqual(_client().http_timeout, 300.0)

    def test_the_timeout_is_configurable_by_environment(self):
        self.assertEqual(_client(env={"JITTEST_HTTP_TIMEOUT": "45"}).http_timeout, 45.0)

    def test_an_explicit_argument_beats_the_environment(self):
        client = _client(env={"JITTEST_HTTP_TIMEOUT": "45"}, http_timeout=600.0)
        self.assertEqual(client.http_timeout, 600.0)

    def test_a_junk_value_falls_back_to_the_default(self):
        self.assertEqual(_client(env={"JITTEST_HTTP_TIMEOUT": "soon"}).http_timeout, 300.0)

    def test_zero_is_not_an_instant_timeout(self):
        """A zero timeout would fail every request immediately. Treat it as
        unset rather than as an instruction to give up."""
        self.assertEqual(_client(env={"JITTEST_HTTP_TIMEOUT": "0"}).http_timeout, 300.0)

    def test_the_configured_timeout_reaches_urlopen(self):
        client = _client(env={"JITTEST_HTTP_TIMEOUT": "45"})
        with mock.patch("jittest.llm.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Response({"ok": True})
            client._post(_URL, {}, {})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 45.0)


if __name__ == "__main__":
    unittest.main()
