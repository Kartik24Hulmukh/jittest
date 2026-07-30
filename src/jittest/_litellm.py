"""Optional LiteLLM backend: `pip install jittest[litellm]` for 2900+ providers."""
from __future__ import annotations

from ._llmbase import BaseLLM, LLMError

__all__ = ["LiteLLMBackend"]


class LiteLLMBackend(BaseLLM):
    """Routes through litellm, which knows each provider's quirks and prices."""

    def __init__(self, model: str, budget_usd: float = 1.0, temperature: float = 0.8):
        super().__init__(model, budget_usd, temperature)
        try:
            import litellm  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional path
            raise LLMError("litellm requested but not installed") from exc

    def complete(self, system: str, user: str, n: int = 1,
                 temperature: float | None = None) -> list[str]:  # pragma: no cover
        import litellm
        self._guard_budget()
        resp = litellm.completion(
            model=self.model,
            temperature=self.temperature if temperature is None else temperature,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            n=n,
        )
        try:
            self.usage.cost_usd += float(litellm.completion_cost(resp) or 0.0)
        except Exception:
            self.usage.priced = False
        self.usage.calls += 1
        return [c["message"]["content"] or "" for c in resp["choices"]]
