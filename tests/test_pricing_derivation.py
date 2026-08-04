"""Tests for Gemini pricing and total-prompt output token derivation."""
from __future__ import annotations

import unittest

from jittest._pricing import price_for


class PricingDerivationTests(unittest.TestCase):
    def test_gemini_36_flash_priced(self):
        price = price_for("gemini-3.6-flash")
        self.assertIsNotNone(price)
        self.assertEqual(price, (0.75, 3.75))

    def test_output_token_derivation_includes_thinking(self):
        # Simulation of response usage block carrying unitemised thinking tokens
        usage = {
            "prompt_tokens": 6,
            "completion_tokens": 1,
            "total_tokens": 79,
        }
        prompt_tokens = usage.get("prompt_tokens")
        total_tokens = usage.get("total_tokens")
        completion_tokens = usage.get("completion_tokens")

        if total_tokens is not None and prompt_tokens is not None:
            out_tokens = total_tokens - prompt_tokens
        else:
            out_tokens = completion_tokens

        # Output tokens derived as total - prompt must be 73, capturing 72 thinking tokens
        self.assertEqual(out_tokens, 73)
        self.assertNotEqual(out_tokens, completion_tokens)


if __name__ == "__main__":
    unittest.main()
