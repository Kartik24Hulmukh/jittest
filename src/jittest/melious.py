"""Melious model router: catalogue-aware failover with bounded request budgets.

The router is the production transport for melious/* models via HTTPLLM: it
validates HTTPS endpoints, bounds max_tokens, fails over retired models,
escalates truncated responses, and limits concurrent dispatch per model.
Transport errors map to TransportError; budgets are checked before and after
each request. HTTP phase timeouts are not hard wall-clock cancellation.

Import this module directly (jittest.melious) — it intentionally does NOT
shadow jittest.llm, which remains the provider-agnostic LLM layer.
"""

from __future__ import annotations

import math
import os
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any

from ._billing import BillingTotals, billing_refusal

MODEL_CEILINGS: dict[str, int] = {
    "glm-5.3": 65536,
    "glm-5.3-flash": 65536,
    "kimi-k3": 65536,
    "qwen3.8-27b": 65536,
}

DEFAULT_MAX_INFLIGHT_PER_MODEL = 4

FAILOVER_CHAINS: dict[str, list[str]] = {
    "glm-4.5": ["glm-5.3"],
}


class MeliousError(Exception):
    """Base class for all router errors."""


class AuthenticationError(MeliousError):
    """Authentication rejected by the catalogue (HTTP 401)."""


class InsufficientCreditsError(MeliousError):
    """Terminal account billing refusal; never retried or failed over."""


class ModelUnavailableError(MeliousError):
    """The requested model is absent from the catalogue (HTTP 404)."""


class ChainExhaustedError(MeliousError):
    """Every leg of the failover chain failed (deadline-bounded; no hang)."""


class DeadlineExceeded(MeliousError):
    """Retry/cooldown exceeded the remaining deadline (no hang)."""


class TransportError(MeliousError):
    """Network/transport failure (timeouts, dropped connections, DNS)."""


@dataclass
class ModelResult:
    text: str
    model: str
    attempts: int = 1
    finish_reason: str = "stop"
    status: int = 200
    usage: dict[str, int] = field(default_factory=dict)
    provider_billing: dict | None = None


def _validate_base(base: str) -> str:
    """Require an HTTPS endpoint without embedded credentials."""
    if "://" not in base:
        base = "https://" + base
    lower = base.lower()
    if not lower.startswith("https://"):
        raise ValueError("API endpoint must be HTTPS without embedded credentials")
    if "@" in base.split("://", 1)[1]:
        raise ValueError("API endpoint must be HTTPS without embedded credentials")
    return base.rstrip("/")


_httpx_module = None


def _httpx() -> Any:
    """Lazily import httpx (optional melious extra)."""
    global _httpx_module
    if _httpx_module is None:
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - depends on install
            raise ImportError(
                "jittest.melious requires the melious extra: pip install -e .[melious]"
            ) from e
        _httpx_module = httpx
    return _httpx_module


class MeliousRouter:
    """Statically-typed router over the Melious chat-completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base: str = "https://api.melious.ai/v1",
        transport: Any | None = None,
        default_deadline: float = 120.0,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        max_inflight_per_model: int = DEFAULT_MAX_INFLIGHT_PER_MODEL,
    ) -> None:
        if (isinstance(max_inflight_per_model, bool)
                or not isinstance(max_inflight_per_model, int)
                or not 1 <= max_inflight_per_model <= 100):
            raise ValueError("max_inflight_per_model must be an integer in 1..100")
        self.api_key = api_key if api_key is not None else os.environ.get("MELIOUS_API_KEY", "")
        self.base = _validate_base(base)
        self.transport = transport
        self.default_deadline = default_deadline
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client: Any | None = None
        self._client_lock = threading.RLock()
        # Active callers retain their slot; completed arbitrary model names do
        # not accumulate process-lifetime scheduler state.
        self._model_slots: weakref.WeakValueDictionary[str, threading.BoundedSemaphore] = (
            weakref.WeakValueDictionary())
        self.max_inflight_per_model = max_inflight_per_model

    def _ensure_client(self) -> Any:
        # httpx clients are thread-safe; construction and publication must also
        # be serialized so concurrent first callers cannot leak separate pools.
        with self._client_lock:
            if self._client is None:
                hx = _httpx()
                self._client = hx.Client(
                    base_url=self.base,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=hx.Timeout(30.0, connect=5.0),
                    transport=self.transport,
                )
            return self._client

    def close(self) -> None:
        with self._client_lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def __enter__(self) -> MeliousRouter:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def list_models(self) -> list[str]:
        """Fetch the live catalogue (Authorization required)."""
        if not self.api_key:
            raise AuthenticationError("auth failed: HTTP 0: MELIOUS_API_KEY is not set (local; 0 network calls)")
        client = self._ensure_client()
        resp = client.get("/models")
        if resp.status_code == 401:
            raise AuthenticationError("auth failed: HTTP 401: catalogue authorization rejected")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return [x.get("id", "") for x in data if isinstance(x, dict)]
        return [x.get("id", "") for x in data.get("data", []) if isinstance(x, dict)]

    def _preflight(self, model: str) -> None:
        if not self.api_key:
            raise AuthenticationError("auth failed: HTTP 0: MELIOUS_API_KEY is not set (local; 0 network calls)")
        ceiling = MODEL_CEILINGS.get(model, 65536)
        if self.max_tokens > ceiling or self.max_tokens <= 0:
            raise ValueError("max_tokens outside configured ceiling")

    def complete(
        self,
        model: str,
        prompt: str,
        *,
        deadline: float | None = None,
        max_tokens: int | None = None,
        truncation_escalation: bool = True,
    ) -> ModelResult:
        """Complete with per-model backpressure; queue time consumes the budget."""
        if not isinstance(model, str) or not model or len(model) > 256:
            raise ValueError("model must be a nonempty bounded string")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be text")
        budget = deadline if deadline is not None else self.default_deadline
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            raise DeadlineExceeded("deadline must be finite and positive")
        if not math.isfinite(budget) or budget <= 0:
            raise DeadlineExceeded("deadline must be finite and positive")
        self._preflight(model)
        started = time.perf_counter()
        with self._client_lock:
            slot = self._model_slots.setdefault(
                model, threading.BoundedSemaphore(self.max_inflight_per_model))
        if not slot.acquire(timeout=min(budget, threading.TIMEOUT_MAX)):
            raise DeadlineExceeded("model dispatch queue exhausted request budget (0 network calls)")
        try:
            remaining = budget - (time.perf_counter() - started)
            if remaining <= 0:
                raise DeadlineExceeded("model dispatch queue exhausted request budget (0 network calls)")
            return self._complete(model, prompt, deadline=remaining, max_tokens=max_tokens,
                                  truncation_escalation=truncation_escalation)
        finally:
            slot.release()

    def _complete(
        self,
        model: str,
        prompt: str,
        *,
        deadline: float | None = None,
        max_tokens: int | None = None,
        truncation_escalation: bool = True,
    ) -> ModelResult:
        """Internal dispatcher; the caller owns and always releases a model slot."""
        t0 = time.perf_counter()
        budget = deadline if deadline is not None else self.default_deadline
        if not math.isfinite(budget) or budget <= 0:
            raise DeadlineExceeded("deadline must be finite and positive")
        tokens = self.max_tokens if max_tokens is None else max_tokens
        if isinstance(tokens, bool) or not isinstance(tokens, int) or not 0 < tokens <= MODEL_CEILINGS.get(model, 65536):
            raise ValueError("max_tokens outside configured ceiling")
        chain = [model] + FAILOVER_CHAINS.get(model, [])
        self._preflight(model)
        client = self._ensure_client()

        last_err: MeliousError | None = None
        for i, leg in enumerate(chain):
            if i > 0 and time.perf_counter() - t0 >= budget:
                raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
            leg_deadline = budget - (time.perf_counter() - t0)
            try:
                return self._complete_leg(
                    client, leg, prompt,
                    deadline=leg_deadline,
                    max_tokens=tokens,
                    truncation_escalation=truncation_escalation,
                )
            except (AuthenticationError, ModelUnavailableError, TransportError) as e:
                if isinstance(e, AuthenticationError):
                    raise
                if i == 0 and len(chain) == 1:
                    raise
                last_err = e
            except DeadlineExceeded as e:
                if i == len(chain) - 1:
                    raise
                last_err = e
            except ChainExhaustedError as e:
                last_err = e
        if last_err is not None:
            raise ChainExhaustedError(
                f"chain exhausted for {model!r} (legs={chain!r}, cause={type(last_err).__name__}) "
                f"under deadline {budget:.2f}s"
            ) from last_err
        raise ChainExhaustedError(
            f"chain exhausted for {model!r} (legs={chain!r}) under deadline {budget:.2f}s"
        )

    def _complete_leg(
        self,
        client: Any,
        model: str,
        prompt: str,
        *,
        deadline: float,
        max_tokens: int,
        truncation_escalation: bool,
    ) -> ModelResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
        }
        leg_start = time.perf_counter()
        attempts = 0
        last_finish = "stop"
        aggregate_usage: dict[str, int] = {}
        billing_totals = BillingTotals()
        escalations = 0
        while True:
            attempts += 1
            elapsed = time.perf_counter() - leg_start
            if elapsed >= deadline:
                raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
            try:
                resp = client.post("/chat/completions", json=payload,
                                   timeout=_httpx().Timeout(deadline - elapsed,
                                                           connect=min(5.0, deadline - elapsed)))
            except Exception as e:
                # A bounded retry tolerates transient DNS/connect failures without
                # pinning a vendor IP or changing global socket behavior.
                remaining = deadline - (time.perf_counter() - leg_start)
                if isinstance(e, _httpx().ConnectError) and attempts < 3 and remaining > 0.1:
                    time.sleep(min(0.1 * attempts, remaining / 2))
                    continue
                raise TransportError(f"network failure (no hang): {type(e).__name__}") from e
            elapsed = time.perf_counter() - leg_start
            if elapsed >= deadline:
                raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
            if resp.status_code == 401:
                raise AuthenticationError("auth failed: HTTP 401: catalogue authorization rejected")
            if billing_refusal(resp.status_code, resp.text):
                raise InsufficientCreditsError("billing refusal: account credits/quota exhausted")
            if resp.status_code in (403, 404, 410):
                raise ModelUnavailableError(
                    f"model {model!r} unavailable: HTTP {resp.status_code}: refused by catalogue"
                )
            if resp.status_code in (429, 500, 502, 503, 504):
                if resp.status_code != 429 and attempts >= 3:
                    raise TransportError(f"provider refused request after bounded retries: HTTP {resp.status_code}")
                cooldown = min(1.5 * attempts, 5.0)
                if elapsed + cooldown >= deadline:
                    raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
                time.sleep(cooldown)
                continue
            if not 200 <= resp.status_code < 300:
                raise TransportError(f"provider refused request: HTTP {resp.status_code}")
            try:
                data = resp.json()
                choices = data.get("choices")
                if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                    raise ValueError("choices must be a nonempty list")
                message = choices[0].get("message")
                if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                    raise ValueError("message.content must be text")
            except (ValueError, AttributeError, TypeError) as exc:
                raise TransportError("malformed completion response") from exc
            billing_totals.add(data.get("billing_cost"))
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise TransportError("malformed completion usage")
            for key, value in usage.items():
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    aggregate_usage[key] = aggregate_usage.get(key, 0) + value
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            finish = (data.get("choices") or [{}])[0].get("finish_reason", "stop")
            last_finish = finish or "stop"
            if truncation_escalation and finish == "length" and max_tokens < 65536:
                escalations += 1
                if escalations >= 3:
                    raise DeadlineExceeded(
                        "truncation escalation exhausted: finish=length after 3 attempts (no hang)"
                    )
                max_tokens = min(max_tokens * 4, 65536)
                payload["max_tokens"] = max_tokens
                continue
            return ModelResult(
                text=text,
                model=model,
                attempts=attempts,
                finish_reason=last_finish,
                status=resp.status_code,
                usage=aggregate_usage,
                provider_billing=billing_totals.as_dict(),
            )
