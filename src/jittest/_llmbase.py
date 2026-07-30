"""The LLM interface and its failure types.

One abstract class, one dataclass, two exceptions. Everything a backend must
provide and everything a caller is allowed to catch, stated in one place.
"""
from __future__ import annotations

from dataclasses import dataclass

from ._llmjson import extract_json

__all__ = ["LLMError", "BudgetExceeded", "Usage", "BaseLLM"]


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    priced: bool = True
    # True when any token count was estimated rather than provider-reported.
    tokens_estimated: bool = False


class BaseLLM:
    def __init__(self, model: str, budget_usd: float = 1.0, temperature: float = 0.8):
        self.model = model
        self.budget_usd = budget_usd
        self.temperature = temperature
        self.usage = Usage()

    def complete(self, system: str, user: str, n: int = 1,
                 temperature: float | None = None) -> list[str]:
        raise NotImplementedError

    def complete_json(self, system: str, user: str,
                      temperature: float | None = None) -> dict | None:
        return extract_json(self.complete(system, user, n=1,
                                          temperature=temperature)[0])

    def _guard_budget(self) -> None:
        if self.usage.cost_usd >= self.budget_usd:
            raise BudgetExceeded(
                f"budget of ${self.budget_usd:.2f} exhausted after "
                f"{self.usage.calls} call(s)")

    def _guard_request_ceiling(self, max_calls: int) -> None:
        """For unpriced models, enforce a request-count ceiling instead of a
        dollar cap, so the pipeline cannot silently run forever."""
        if self.usage.calls >= max_calls:
            raise BudgetExceeded(
                f"request ceiling of {max_calls} call(s) reached for "
                f"unpriced model '{self.model}'")
