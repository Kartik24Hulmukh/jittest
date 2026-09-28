"""Melious model router with failover, bounded deadlines, and hardening.

Turns jittest probes into model calls routed across a failover chain of
Melious catalogue models with:

- HTTPS-only endpoint validation (rejects non-TLS and embedded credentials)
- Catalogue-aware model availability (404 absent -> ModelUnavailableError)
- Preflight bounds validation (max_tokens ceiling, etc.) before any spend
- Truncation escalation: retries a refused/truncated response with more tokens
- Hard wall-clock deadline across retries and failover legs (no hang)
- 429-aware failover with bounded cooldown; no cross-model routing leaks

The router is deterministic and offline-testable: the HTTP layer is injected
via ``transport`` (_httpx().MockTransport) so unit tests exercise failover and
deadline logic without network access.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

_httpx_module = None


def _httpx() -> Any:
    """Lazily import httpx (optional extra).

    The core jittest package stays dependency-free; the Melious router is
    enabled by installing the \"melious\" extra (httpx). Importing
    jittest.llm.melious_router without httpx raises ImportError with a clear
    install hint instead of failing at package import time.
    """
    global _httpx_module
    if _httpx_module is None:
        try:
            import httpx  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - depends on install
            raise ImportError(
                "jittest.llm.melious_router requires the 'melious' extra: "
                "pip install -e .[melious]  (httpx>=0.28)"
            ) from e
        _httpx_module = httpx
    return _httpx_module


MODEL_CEILINGS: dict[str, int] = {
    "glm-5.3": 65536,
    "glm-5.3-flash": 65536,
    "kimi-k3": 65536,
    "qwen3.8-27b": 65536,
}

FAILOVER_CHAINS: dict[str, list[str]] = {
    # retired/edge models fail over to a healthy primary
    "glm-4.5": ["glm-5.3"],
}


class MeliousError(Exception):
    """Base class for all router errors."""


class AuthenticationError(MeliousError):
    """Authentication rejected by the catalogue (HTTP 401)."""


class ModelUnavailableError(MeliousError):
    """The requested model is absent from the catalogue (HTTP 404)."""


class ChainExhaustedError(MeliousError):
    """Every leg of the failover chain failed (deadline-bounded; no hang)."""


class TransportError(MeliousError):
    """Network/transport failure (timeouts, dropped connections, DNS).

    Mapped from httpx transport exceptions so a dropped network behaves like a
    failed leg: it fails over when a fallback exists and raises cleanly (never
    an uncaught httpx exception) when the chain is exhausted.
    """


class DeadlineExceeded(MeliousError):
    """Retry/cooldown exceeded the remaining deadline (no hang)."""


@dataclass
class ModelResult:
    text: str
    model: str
    attempts: int = 1
    finish_reason: str = "stop"
    status: int = 200
    usage: dict[str, int] = field(default_factory=dict)


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


def _catalogue_url(base: str) -> str:
    return _validate_base(base) + "/models"


class MeliousRouter:
    """Statically-typed router over the Melious chat-completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base: str = "https://api.melious.ai/v1",
        transport: _httpx().BaseTransport | None = None,
        default_deadline: float = 120.0,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.environ.get("MELIOUS_API_KEY", "")
        self.base = _validate_base(base)
        self.transport = transport
        self.default_deadline = default_deadline
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client: _httpx().Client | None = None

    def _ensure_client(self) -> _httpx().Client:
        if self._client is None:
            self._client = _httpx().Client(
                base_url=self.base,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=_httpx().Timeout(30.0, connect=5.0),
                transport=self.transport,
            )
        return self._client

    def close(self) -> None:
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
            return [m.get("id", "") for m in data if isinstance(m, dict)]
        return [m.get("id", "") for m in data.get("data", []) if isinstance(m, dict)]

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
        """Complete ``prompt`` on ``model`` with failover and a hard deadline.

        Raises AuthenticationError on 401, ModelUnavailableError on 404-absent,
        ChainExhaustedError when every chain leg fails, DeadlineExceeded when
        retries/cooldown would exceed the remaining deadline (never hangs).
        """
        t0 = time.perf_counter()
        budget = deadline if deadline is not None else self.default_deadline
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
                    max_tokens=max_tokens or self.max_tokens,
                    truncation_escalation=truncation_escalation,
                )
            except (AuthenticationError, ModelUnavailableError, TransportError) as e:
                # terminal per leg: a missing/slow model fails over; auth is fatal
                if isinstance(e, AuthenticationError):
                    raise
                if i == 0 and len(chain) == 1:
                    # a direct (non-failover) call whose only leg failed:
                    # propagate the direct error so callers see the real cause
                    raise
                # a fallback leg failed -> the chain itself is exhausted (or fails over)
                last_err = e
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
        client: _httpx().Client,
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
        while True:
            attempts += 1
            elapsed = time.perf_counter() - leg_start
            if elapsed >= deadline:
                raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
            try:
                resp = client.post("/chat/completions", json=payload)
            except _httpx().HTTPError as e:
                raise TransportError(
                    f"network failure (no hang): {type(e).__name__}"
                ) from e
            elapsed = time.perf_counter() - leg_start
            if elapsed >= deadline:
                raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
            if resp.status_code == 401:
                raise AuthenticationError("auth failed: HTTP 401: catalogue authorization rejected")
            if resp.status_code == 404:
                raise ModelUnavailableError(
                    f"model {model!r} unavailable: HTTP 404: absent from catalogue (0 spend)"
                )
            if resp.status_code == 429:
                # bounded cooldown; if it would exceed the leg deadline, stop
                cooldown = min(1.5 * attempts, 5.0)
                if elapsed + cooldown >= deadline:
                    raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
                time.sleep(cooldown)
                continue
            resp.raise_for_status()
            data = resp.json()
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            finish = (data.get("choices") or [{}])[0].get("finish_reason", "stop")
            last_finish = finish or "stop"
            if truncation_escalation and finish == "length" and max_tokens < 65536:
                if attempts >= 3:
                    raise DeadlineExceeded(
                        "truncation escalation exhausted: finish=length after 3 attempts (no hang)"
                    )
                # escalation: retry with more tokens (bounded by both deadline and attempt cap)
                max_tokens = min(max_tokens * 4, 65536)
                payload["max_tokens"] = max_tokens
                if elapsed >= deadline:
                    raise DeadlineExceeded("retry/cooldown exceeds remaining deadline (no hang)")
                continue
            return ModelResult(
                text=text,
                model=model,
                attempts=attempts,
                finish_reason=last_finish,
                status=resp.status_code,
                usage=data.get("usage", {}),
            )


def router_from_env(**kw: Any) -> MeliousRouter:
    return MeliousRouter(**kw)