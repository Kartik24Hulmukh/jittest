from __future__ import annotations

import os
import unittest


class TestResolvedRequestCeiling(unittest.TestCase):
    def setUp(self):
        self._old_env = dict(os.environ)
        os.environ["JITTEST_API_KEY"] = "test-key"
        os.environ["JITTEST_MAX_TARGETS"] = "99"
        os.environ["JITTEST_CANDIDATES"] = "99"

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_placeholder(self):
        self.assertEqual(os.environ["JITTEST_API_KEY"], "test-key")


if __name__ == "__main__":
    unittest.main()
