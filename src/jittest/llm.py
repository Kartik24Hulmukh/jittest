"""Model access over urllib: Anthropic Messages and any OpenAI-compatible API.

Phase C uses HTTPLLM directly with explicit BudgetManager dependency injection.
"""

from __future__ import annotations

import dataclasses
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from ._llmbase import BaseLLM, BudgetExceeded, LLMError, Usage
from ._llmcache import _Cache
from ._llmjson import extract_json, strip_code_fence
from ._pricing import PRICES, estimate_tokens, price_for
from .budget import BudgetExceededError, BudgetManager


class RateLimitedError(LLMError):
    """Raised when the LLM provider rate limits requests after retries."""


class TimedOutError(LLMError):
    """Raised when the LLM provider times out on all retries."""


__all__ = [
    "LLMError",
    "RateLimitedError",
    "TimedOutError",
    "BudgetExceeded",
    "Usage",
    "BaseLLM",
    "HTTPLLM",
    "DryRunLLM",
    "build_llm",
    "FrozenRunConfig",
    "extract_json",
    "strip_code_fence",
    "PRICES",
    "price_for",
    "estimate_tokens",
    "retry_after_seconds",
]


def retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if not raw:
        return None
    raw = str(raw).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


@dataclasses.dataclass(frozen=True)
class FrozenRunConfig:
    """Immutable frozen Phase C run configuration (Section C5-C6). Environment variables cannot alter this."""

    provider: str = "Mistral AI"
    model_name: str = "codestral-2508"
    api_endpoint: str = "https://api.mistral.ai/v1/chat/completions"
    temperature: float = 0.0
    top_p: float = 1.0
    max_attempts: int = 3
    timeout_seconds: float = 120.0
    concurrency_limit: int = 4
    parser_failure_policy: str = "abort_on_parse_error_and_mark_unverified"


_RETRYABLE = {408, 409, 429, 500, 502, 503, 529}
_RATE_LIMITED = {429, 503}
_RATE_LIMIT_FLOOR = 5.0


class DryRunLLM(BaseLLM):
    """A model-shaped object that costs nothing and needs no network."""

    DEFAULT = "# NO_CANDIDATE  (dry run: no model was called)" + chr(10)

    def __init__(self, scripted: list[str] | None = None, model: str = "dry-run"):
        super().__init__(model, budget_usd=0.0, temperature=0.0)
        self.scripted = list(scripted or [])
        self.calls: list[tuple[str, str]] = []
        self._i = 0

    def complete(
        self, system: str, user: str, n: int = 1, temperature: float | None = None
    ) -> list[str]:
        self.calls.append((system, user))
        self.usage.calls += 1
        if self._i < len(self.scripted):
            reply = self.scripted[self._i]
            self._i += 1
        else:
            reply = self.scripted[-1] if self.scripted else self.DEFAULT
        return [reply] * max(1, n)


class HTTPLLM(BaseLLM):
    def __init__(
        self,
        model: str,
        budget_manager: BudgetManager | None = None,
        api_key: str | None = None,
        temperature: float = 0.0,
        cache_path: Path | str | None = None,
        config: FrozenRunConfig | None = None,
        budget_usd: float = 1.0,
        request_ceiling: int | None = None,
        max_attempts: int | None = None,
        timeout: float | None = None,
    ):
        self._unpriced = price_for(model) is None
        if self._unpriced and request_ceiling is None:
            request_ceiling = 6
        if budget_manager is None:
            max_req = request_ceiling if request_ceiling is not None else 1080
            budget_manager = BudgetManager(
                authorized_spend_ceiling_usd=budget_usd, max_requests=max_req
            )
        super().__init__(model, float(budget_manager.authorized_spend_ceiling_usd), temperature)
        self.config = config or FrozenRunConfig()
        self.budget_manager = budget_manager
        self.request_ceiling = (
            request_ceiling if request_ceiling is not None else budget_manager.max_requests
        )

        provider, _, name = model.partition("/")
        if not name:
            provider, name = ("anthropic" if "claude" in model else "openai"), model
        self.provider = provider
        self.model_name = name
        self.api_key = api_key or self._find_key(provider)

        api_base_env = os.getenv("JITTEST_API_BASE")
        if api_base_env:
            self.base_url = api_base_env.rstrip("/")
            self.api_model = model
        elif provider == "anthropic":
            self.base_url = "https://api.anthropic.com/v1"
            self.api_model = name
        elif provider == "mistral":
            self.base_url = "https://api.mistral.ai/v1"
            self.api_model = self.config.model_name
        else:
            self.base_url = "https://api.openai.com/v1"
            self.api_model = name

        self.cache = _Cache(cache_path)
        self.max_attempts = max_attempts if max_attempts is not None else self.config.max_attempts

        if timeout is not None:
            self.http_timeout = float(timeout) if float(timeout) > 0 else 300.0
        else:
            env_t = os.getenv("JITTEST_HTTP_TIMEOUT")
            if env_t:
                try:
                    tv = float(env_t)
                    self.http_timeout = tv if tv > 0 else 300.0
                except ValueError:
                    self.http_timeout = self.config.timeout_seconds
            else:
                self.http_timeout = self.config.timeout_seconds

        self._last_request_at: float | None = None
        self.rate_limit_waits = 0
        self.rate_limit_seconds = 0.0
        self.timeout_retries = 0
        self.transport_retries = 0
        self.slept: list[float] = []

        if not self.api_key and provider != "ollama":
            raise LLMError("no API key found. Set JITTEST_API_KEY, or run with --dry-run.")

    @staticmethod
    def _find_key(provider: str) -> str | None:
        for name in (
            "JITTEST_API_KEY",
            f"{provider.upper()}_API_KEY",
            "MISTRAL_API_KEY",
            "OPENAI_API_KEY",
        ):
            if os.getenv(name):
                return os.environ[name]
        return None

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.slept.append(seconds)
            time.sleep(seconds)

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        if "top_p" not in payload:
            payload["top_p"] = self.config.top_p

        data = json.dumps(payload).encode("utf-8")
        proj_in = estimate_tokens(json.dumps(payload))
        proj_out = payload.get("max_tokens", 2000)

        last: Exception | None = None
        last_code: int | None = None
        for attempt in range(self.max_attempts):
            try:
                res_id = self.budget_manager.reserve_budget(
                    projected_input_tokens=proj_in, projected_output_tokens=proj_out
                )
            except BudgetExceededError as exc:
                if self._unpriced and (
                    self.usage.calls >= self.request_ceiling
                    or self.budget_manager.executed_requests + self.budget_manager.reserved_requests
                    >= self.request_ceiling
                ):
                    raise BudgetExceeded("unpriced model request ceiling reached") from exc
                raise BudgetExceeded(str(exc)) from exc

            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            self._last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    usage = res_body.get("usage", {})
                    actual_in = usage.get("prompt_tokens") or usage.get("input_tokens")
                    actual_out = usage.get("completion_tokens") or usage.get("output_tokens")

                    self.budget_manager.reconcile_reservation(res_id, actual_in, actual_out)
                    return res_body
            except urllib.error.HTTPError as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                last, last_code = exc, exc.code
                if exc.code not in _RETRYABLE:
                    detail = exc.read().decode("utf-8", "ignore")[:400]
                    raise LLMError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
            except TimeoutError as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                last, last_code = exc, None
                self.timeout_retries += 1
            except urllib.error.URLError as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                last, last_code = exc, None
            except (http.client.HTTPException, ConnectionError) as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                last, last_code = exc, None
                if attempt < self.max_attempts - 1:
                    self.transport_retries += 1
            except Exception as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                raise exc

            if attempt == self.max_attempts - 1:
                break

            ra_secs = (
                retry_after_seconds(last) if isinstance(last, urllib.error.HTTPError) else None
            )
            delay = ra_secs if ra_secs is not None else 2.0**attempt
            if last_code in _RATE_LIMITED:
                delay = min(delay, 20.0) if ra_secs is None else min(delay, 60.0)
            self._sleep(delay)

        if last_code in _RATE_LIMITED:
            min_int = os.getenv("JITTEST_MIN_REQUEST_INTERVAL")
            msg = f"rate limited by {self.provider} after {self.max_attempts} attempts."
            if min_int:
                msg += " Consider tuning JITTEST_MIN_REQUEST_INTERVAL."
            raise RateLimitedError(msg)
        if isinstance(last, TimeoutError):
            raise TimedOutError(
                f"{self.provider} did not answer within {self.http_timeout:.0f}s on any attempt."
            )
        raise LLMError(f"model request failed after retries: {last}")

    def complete(
        self, system: str, user: str, n: int = 1, temperature: float | None = None
    ) -> list[str]:
        if self._unpriced and (
            self.usage.calls >= self.request_ceiling
            or (self.budget_manager.executed_requests + self.budget_manager.reserved_requests)
            >= self.request_ceiling
        ):
            raise BudgetExceeded("unpriced model request ceiling reached")

        temp = self.temperature if temperature is None else temperature
        key = hashlib.sha256(
            f"{self.provider}|{self.model_name}|{system}|{user}|{n}|{temp}".encode()
        ).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return json.loads(cached)

        endpoint = (
            f"{self.base_url}/messages"
            if self.provider == "anthropic"
            else f"{self.base_url}/chat/completions"
        )
        headers = (
            {
                "content-type": "application/json",
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
            }
            if self.provider == "anthropic"
            else {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key or ''}",
            }
        )

        outputs: list[str] = []
        for _ in range(max(1, n)):
            body = self._post(
                endpoint,
                {
                    "model": self.api_model,
                    "temperature": temp,
                    "top_p": self.config.top_p,
                    "max_tokens": 2048,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                headers,
            )
            choices = body.get("choices", [])
            if choices:
                text = choices[0]["message"]["content"]
            elif "content" in body:
                text = body["content"][0]["text"]
            else:
                text = ""
            outputs.append(text or "")

        self.cache.put(key, json.dumps(outputs))
        return outputs


def build_llm(
    model: str,
    budget_manager: BudgetManager | None = None,
    dry_run: bool = False,
    temperature: float = 0.0,
    cache_path: Path | str | None = None,
    api_key: str | None = None,
    budget_usd: float = 1.0,
    request_ceiling: int | None = None,
    **kwargs,
) -> BaseLLM:
    """Build LLM instance with explicit BudgetManager dependency injection (Section C1)."""
    if dry_run:
        return DryRunLLM(model=f"{model} (dry run)")
    if budget_manager is None:
        max_req = request_ceiling if request_ceiling is not None else 1080
        budget_manager = BudgetManager(
            authorized_spend_ceiling_usd=budget_usd, max_requests=max_req
        )
    return HTTPLLM(
        model,
        budget_manager=budget_manager,
        api_key=api_key,
        temperature=temperature,
        cache_path=cache_path,
        request_ceiling=request_ceiling,
        **kwargs,
    )
