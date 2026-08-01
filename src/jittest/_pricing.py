"""Model pricing: a small built-in table, an operator override, and an estimate.

Kept apart from the transport code so the arithmetic of what a run costs can
change without dragging model I/O into review, and vice versa.
"""
from __future__ import annotations

import os

__all__ = ["PRICES", "price_for", "estimate_tokens"]


# USD per million tokens (input, output). Unknown models are not guessed: we
# say so in the report instead of printing a confident wrong number.
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
            if stated is not None and stated[0] >= 0 and stated[1] >= 0:
                return stated
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
