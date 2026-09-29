"""Model pricing: a small built-in table, an operator override, and an estimate.

Kept apart from the transport code so the arithmetic of what a run costs can
change without dragging model I/O into review, and vice versa.
"""
from __future__ import annotations

import math
import os

__all__ = ["PRICES", "price_for", "estimate_tokens"]


# USD per million tokens (input, output). Unknown models are not guessed: we
# say so in the report instead of printing a confident wrong number.
# Gemini pricing updated 2026-08-05 from https://ai.google.dev/gemini-api/docs/pricing
# Devstral-2512 pricing updated 2026-08-05 from https://mistral.ai/news/devstral-2-vibe-cli/
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-opus-4-1": (15.00, 75.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "o4-mini": (1.10, 4.40),
    "deepseek-chat": (0.27, 1.10),
    "qwen-2.5-coder-32b": (0.09, 0.09),
    "moonshotai/kimi-k3": (3.00, 15.00),
    "gemini-3.6-flash": (1.50, 7.50),
    "devstral-2512": (0.40, 2.00),
}


# Vendor list rates verified at https://melious.ai/pricing on 2026-09-29.
# Currency conversion must be stated by the operator; no invented USD rate.
MELIOUS_PRICES_EUR: dict[str, tuple[float, float]] = {
    "glm-5.3-flash": (0.10, 0.40),
    "glm-5.3": (1.00, 3.00),
    "kimi-k3": (2.80, 14.00),
    "qwen3.8-27b": (0.40, 2.40),
}


def price_for(model: str) -> tuple[float, float] | None:
    """USD per million (input, output) tokens for a model, or None.

    The built-in table will always be out of date, and it will never contain
    the model somebody is actually using behind a gateway. Rather than guess
    a price - which produces a confident wrong number in a cost report - the
    operator can state one:

        JITTEST_MODEL_PRICE="0.60,2.20"

    A stated price is used as-is and turns the dollar cap back on. Without
    one the model stays unpriced, and the run says so.
    """
    raw = os.getenv("JITTEST_MODEL_PRICE", "").strip()
    if raw:
        parts = [x.strip() for x in raw.replace("/", ",").split(",")]
        if len(parts) == 2:
            try:
                stated = (float(parts[0]), float(parts[1]))
            except ValueError:
                stated = None
            if stated is not None and all(math.isfinite(x) and x >= 0 for x in stated):
                return stated
    # Exact bare IDs or explicitly namespaced Melious IDs only.
    bare = model.removeprefix("melious/")
    if bare in MELIOUS_PRICES_EUR and ("/" not in model or model.startswith("melious/")):
        try:
            fx = float(os.environ["JITTEST_EUR_USD"])
        except (KeyError, ValueError):
            return None
        if not math.isfinite(fx) or fx <= 0:
            return None
        in_price, out_price = MELIOUS_PRICES_EUR[bare]
        return in_price * fx, out_price * fx
    for key, price in PRICES.items():
        if key in model:
            return price
    return None


def estimate_tokens(text: str) -> int:
    """A deliberately crude character-based token estimate.

    Four characters per token is wrong for every model, and it is wrong by a
    small enough margin to be useful for a budget guard. It exists only for
    endpoints that return no usage block at all; anything that reports real
    numbers uses those instead, and the report distinguishes the two.
    """
    return max(1, (len(text or "") + 3) // 4)
