"""Permanent model refusal (HTTP 401/403/404/410) stops generation.

Receipt: eval run 36346472249. The configured model reached end of life and
returned HTTP 410 on every request, the pipeline kept asking for every
candidate of every target, and the eval summary recorded the cause as "ok".
"""
from __future__ import annotations

import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval.unmeasured import tally  # noqa: E402
from jittest.llm import (  # noqa: E402
    HTTPLLM,
    DryRunLLM,
    LLMError,
    ModelUnavailableError,
)
from jittest.pipeline import run  # noqa: E402

from .helpers import FixtureRepo  # noqa: E402
from .test_pipeline import cfg  # noqa: E402


def _http_error(code: int) -> urllib.error.HTTPError:
    body = io.BytesIO(b'{"status": %d, "detail": "end of life"}' % code)
    return urllib.error.HTTPError("http://x", code, "err", {}, body)


class PermanentHTTPCodes(unittest.TestCase):
    def test_410_401_403_404_raise_model_unavailable_without_retry(self):
        for code in (401, 403, 404, 410):
            llm = HTTPLLM("m", api_key="k", budget_usd=1.0)
            fake = mock.Mock(side_effect=_http_error(code))
            with mock.patch("urllib.request.urlopen", fake), \
                    self.assertRaises(ModelUnavailableError) as ctx:
                llm._post("http://x", {}, {})
            self.assertIn(str(code), str(ctx.exception))
            self.assertEqual(fake.call_count, 1, f"HTTP {code} must not be retried")
            self.assertIsInstance(ctx.exception, LLMError)

    def test_400_is_still_a_plain_model_error(self):
        llm = HTTPLLM("m", api_key="k", budget_usd=1.0)
        with mock.patch("urllib.request.urlopen", side_effect=_http_error(400)), \
                self.assertRaises(LLMError) as ctx:
            llm._post("http://x", {}, {})
        self.assertNotIsInstance(ctx.exception, ModelUnavailableError)


class PipelineStopsAsking(unittest.TestCase):
    def test_generation_stops_after_first_permanent_refusal(self):
        calls = []

        class GoneLLM(DryRunLLM):
            def complete(self, system, user, n=1, temperature=None):
                calls.append(1)
                raise ModelUnavailableError("HTTP 410 from z-ai: Gone")

        with FixtureRepo() as repo:
            report = run(repo.path, repo.base, repo.head,
                         cfg(candidates_per_target=4), GoneLLM())
        self.assertEqual(len(calls), 1)
        self.assertEqual(report.discarded.get("model_unavailable"), 1)
        self.assertEqual(report.diff_status, "model_unavailable")
        self.assertTrue(any("model unavailable" in e for e in report.errors))


class EvalCauseIsNotOk(unittest.TestCase):
    def test_tally_names_model_unavailable(self):
        class Row:
            status = "not_measured"
            diff_status = "model_unavailable"

        self.assertEqual(tally([Row(), Row()]), {"model_unavailable": 2})


if __name__ == "__main__":
    unittest.main()
