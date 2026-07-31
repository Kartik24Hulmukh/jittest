from __future__ import annotations

import os
import unittest

from jittest.llm import HTTPLLM, BudgetExceeded


class TestResolvedRequestCeiling(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        os.environ["JITTEST_API_KEY"] = "test-key"
        os.environ["JITTEST_MAX_TARGETS"] = "99"
        os.environ["JITTEST_CANDIDATES"] = "99"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_explicit_request_ceiling_beats_raw_env(self):
        llm = HTTPLLM("z-ai/glm-5.2", api_key="test-key", request_ceiling=2)
        llm.usage.calls = 2

        with self.assertRaises(BudgetExceeded) as ctx:
            llm.complete("system", "user")

        self.assertIn("request ceiling", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
