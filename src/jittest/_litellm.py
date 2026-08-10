"""Optional LiteLLM backend (Disabled in Phase C per Section C4)."""

from __future__ import annotations

from ._llmbase import BaseLLM, LLMError

__all__ = ["LiteLLMBackend"]


class LiteLLMBackend(BaseLLM):
    """LiteLLM backend route disabled in Phase C."""

    def __init__(
        self, model: str, budget_manager=None, budget_usd: float = 0.0, temperature: float = 0.0
    ):
        super().__init__(model, budget_usd, temperature)
        raise LLMError("LiteLLM Phase C path and provider fallbacks are disabled in R2A.")

    def complete(
        self, system: str, user: str, n: int = 1, temperature: float | None = None
    ) -> list[str]:
        raise LLMError("LiteLLM Phase C path and provider fallbacks are disabled in R2A.")
