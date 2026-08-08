"""Model access over urllib: Anthropic Messages and any OpenAI-compatible API.

Phase C uses HTTPLLM directly with explicit BudgetManager dependency injection.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


_RETRYABLE = {408, 409, 429, 500, 502, 503, 529}
_RATE_LIMITED = {429, 503}
_RATE_LIMIT_FLOOR = 5.0
_DEFAULT_MAX_ATTEMPTS = 8
_DEFAULT_MAX_SLEEP = 90.0
_DEFAULT_HTTP_TIMEOUT = 300.0


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
        http_timeout: float | None = None,
        min_request_interval: float | None = None,
        max_sleep: float | None = None,
        phase_c: bool = False,
        **kwargs,
    ):
        if kwargs:
            raise TypeError(f"Unknown keyword arguments rejected: {set(kwargs)}")

        is_frozen = phase_c or config is not None
        if is_frozen:
            if budget_manager is None:
                raise ValueError("Phase C frozen mode requires explicit BudgetManager dependency injection")

            valid_models = ("mistral/codestral-2508", "codestral-2508")
            if model not in valid_models:
                raise ValueError(
                    f"Phase C mode requires model 'mistral/codestral-2508' or 'codestral-2508', got {model!r}"
                )

            banned_envs = [
                "JITTEST_MODEL",
                "JITTEST_BUDGET_USD",
                "JITTEST_MAX_TARGETS",
                "JITTEST_CANDIDATES",
                "JITTEST_RISK_THRESHOLD",
                "JITTEST_SANDBOX",
                "JITTEST_SANDBOX_BACKEND",
                "JITTEST_SANDBOX_IMAGE",
                "JITTEST_API_BASE",
                "JITTEST_MAX_RETRIES",
                "JITTEST_RETRY_MAX_SLEEP",
                "JITTEST_MIN_REQUEST_INTERVAL",
                "JITTEST_HTTP_TIMEOUT",
            ]
            found_envs = [env for env in banned_envs if os.getenv(env)]
            if found_envs:
                raise ValueError(f"Environment overrides rejected in Phase C frozen mode: {found_envs}")

            if temperature != 0.0:
                raise ValueError(f"Temperature override {temperature} rejected in Phase C frozen mode")

        self._unpriced = price_for(model) is None
        if budget_manager is None:
            max_req = request_ceiling if request_ceiling is not None else 1080
            budget_manager = BudgetManager(
                authorized_spend_ceiling_usd=budget_usd, max_requests=max_req
            )

        super().__init__(model, float(budget_manager.authorized_spend_ceiling_usd), temperature)
        self.config = config or FrozenRunConfig()
        self.budget_manager = budget_manager
        self.phase_c = is_frozen
        self.request_ceiling = request_ceiling

        provider, _, name = model.partition("/")
        if not name:
            provider, name = ("anthropic" if "claude" in model else "openai"), model
        self.provider = provider
        self.model_name = name
        self.api_key = api_key or self._find_key(provider)

        api_base_env = os.getenv("JITTEST_API_BASE")
        if api_base_env and not is_frozen:
            self.base_url = api_base_env.rstrip("/")
            self.api_model = model
        elif provider == "anthropic":
            self.base_url = "https://api.anthropic.com/v1"
            self.api_model = name
        elif provider == "mistral":
            self.base_url = self.config.api_endpoint.rsplit("/chat/completions", 1)[0]
            self.api_model = self.config.model_name
        else:
            self.base_url = "https://api.openai.com/v1"
            self.api_model = name

        self.cache = _Cache(None if is_frozen else cache_path)

        if is_frozen:
            self.max_attempts = self.config.max_attempts
            self.max_sleep = _DEFAULT_MAX_SLEEP
            self.min_request_interval = 0.0
            self.http_timeout = float(self.config.timeout_seconds)
        else:
            if max_attempts is not None:
                self.max_attempts = max_attempts
            else:
                self.max_attempts = _env_int("JITTEST_MAX_RETRIES", _DEFAULT_MAX_ATTEMPTS)

            if max_sleep is not None:
                self.max_sleep = max_sleep
            else:
                self.max_sleep = _env_float("JITTEST_RETRY_MAX_SLEEP", _DEFAULT_MAX_SLEEP)

            if min_request_interval is not None:
                self.min_request_interval = min_request_interval
            else:
                self.min_request_interval = _env_float("JITTEST_MIN_REQUEST_INTERVAL", 0.0)

            eff_timeout = http_timeout if http_timeout is not None else timeout
            if eff_timeout is not None:
                self.http_timeout = float(eff_timeout) if float(eff_timeout) > 0 else 300.0
            else:
                env_t = os.getenv("JITTEST_HTTP_TIMEOUT")
                if env_t:
                    try:
                        tv = float(env_t)
                        self.http_timeout = tv if tv > 0 else 300.0
                    except ValueError:
                        self.http_timeout = _DEFAULT_HTTP_TIMEOUT
                else:
                    self.http_timeout = _DEFAULT_HTTP_TIMEOUT

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
            "ANTHROPIC_API_KEY",
        ):
            if os.getenv(name):
                return os.environ[name]
        return None

    def complete(
        self, system: str, user: str, n: int = 1, temperature: float | None = None
    ) -> list[str]:
        if self.phase_c and temperature is not None and temperature != 0.0:
            raise ValueError(f"Temperature override {temperature} rejected in Phase C frozen mode")

        if self._unpriced:
            ceiling = self.request_ceiling
            if ceiling is None:
                ceiling = (int(os.getenv("JITTEST_MAX_TARGETS", "5")) *
                           int(os.getenv("JITTEST_CANDIDATES", "4")) + 5)
            self._guard_request_ceiling(ceiling)
        else:
            self._guard_budget()

        temp = self.temperature if temperature is None else temperature
        if self.provider == "anthropic":
            url = f"{self.base_url}/messages"
            headers = {
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            payload = {
                "model": self.api_model,
                "messages": [{"role": "user", "content": user}],
                "max_tokens": 4096,
                "temperature": temp,
            }
            if system:
                payload["system"] = system
            res = self._post(url, payload, headers)
            content = res.get("content", [])
            text = content[0].get("text", "") if content else ""
            return [text] * max(1, n)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        payload = {
            "model": self.api_model,
            "messages": messages,
            "temperature": temp,
            "top_p": self.config.top_p,
            "n": n,
        }
        res = self._post(url, payload, headers)
        choices = res.get("choices", [])
        return [c.get("message", {}).get("content", "") for c in choices] or [""]

    def _price(self) -> tuple[float, float] | None:
        return price_for(self.model_name) or price_for(self.model)

    def _account(self, input_tokens: int, output_tokens: int, estimated: bool = False) -> None:
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.calls += 1
        if estimated:
            self.usage.tokens_estimated = True
        price = self._price()
        if price is None:
            self.usage.priced = False
            return
        self.usage.cost_usd += (input_tokens * price[0] + output_tokens * price[1]) / 1e6

    def _account_response(self, reported_in: Any, reported_out: Any, prompt: str, text: str) -> None:
        try:
            in_tokens = int(reported_in or 0)
            out_tokens = int(reported_out or 0)
        except (TypeError, ValueError):
            in_tokens = out_tokens = 0

        if in_tokens or out_tokens:
            self._account(in_tokens, out_tokens)
            return

        if getattr(self, "phase_c", False):
            self.usage.unverified = True

        self._account(estimate_tokens(prompt), estimate_tokens(text), estimated=True)

    def _sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.slept.append(seconds)
            time.sleep(seconds)

    def _pace(self) -> None:
        if self.min_request_interval <= 0 or self._last_request_at is None:
            return
        gap = self.min_request_interval - (time.monotonic() - self._last_request_at)
        if gap > 0:
            self._sleep(gap)

    def _backoff(self, attempt: int, requested: float | None, rate_limited: bool) -> float:
        if requested is not None:
            return min(requested, self.max_sleep)
        base = 2.0**attempt
        if rate_limited:
            base = max(base, _RATE_LIMIT_FLOOR)
        return min(base, self.max_sleep)

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        if "top_p" not in payload:
            payload["top_p"] = self.config.top_p

        data = json.dumps(payload).encode("utf-8")
        proj_in = estimate_tokens(json.dumps(payload))
        proj_out = payload.get("max_tokens", 2000)

        last: Exception | None = None
        last_code: int | None = None
        for attempt in range(self.max_attempts):
            requested: float | None = None
            self._pace()

            try:
                res_id = self.budget_manager.reserve_budget(
                    projected_input_tokens=proj_in, projected_output_tokens=proj_out
                )
            except BudgetExceededError as exc:
                if self._unpriced and self.request_ceiling is not None and (
                    self.usage.calls >= self.request_ceiling
                    or self.budget_manager.executed_requests + self.budget_manager.reserved_requests
                    >= self.request_ceiling
                ):
                    raise BudgetExceeded("unpriced model request ceiling reached") from exc
                raise BudgetExceeded(str(exc)) from exc

            # Persist dispatch_started immediately BEFORE network call
            self.budget_manager.record_dispatch_start(res_id)

            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            self._last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                    res_body = json.loads(resp.read().decode("utf-8"))
                    usage = res_body.get("usage", {})
                    actual_in = usage.get("prompt_tokens") or usage.get("input_tokens")
                    actual_out = usage.get("completion_tokens") or usage.get("output_tokens")

                    if (actual_in is None or actual_out is None) and getattr(self, "phase_c", False):
                        self.usage.unverified = True

                    self.budget_manager.reconcile_reservation(res_id, actual_in, actual_out)
                    self._account_response(actual_in, actual_out, json.dumps(payload), json.dumps(res_body))
                    return res_body
            except json.JSONDecodeError as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                raise LLMError(f"Malformed JSON response from {self.provider}: {exc}") from exc
            except urllib.error.HTTPError as exc:
                self.budget_manager.reconcile_reservation(
                    res_id, is_unknown_or_partial_failure=True
                )
                last, last_code = exc, exc.code
                if exc.code not in _RETRYABLE:
                    detail = exc.read().decode("utf-8", "ignore")[:400]
                    raise LLMError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
                if exc.code in _RATE_LIMITED:
                    requested = retry_after_seconds(exc)
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

            rate_limited = last_code in _RATE_LIMITED
            delay = self._backoff(attempt, requested, rate_limited)
            if rate_limited:
                self.rate_limit_waits += 1
                self.rate_limit_seconds += delay
            self._sleep(delay)

        if last_code in _RATE_LIMITED:
            raise RateLimitedError(
                f"rate limited by {self.provider} after {self.max_attempts} attempts "
                f"({self.rate_limit_waits} 429/503 responses). Try increasing JITTEST_RETRY_MAX_SLEEP or JITTEST_MIN_REQUEST_INTERVAL"
            )
        if isinstance(last, TimeoutError):
            raise TimedOutError(
                f"timed out connecting to {self.provider} after {self.max_attempts} attempts "
                f"({self.timeout_retries} read timeouts). Try increasing JITTEST_HTTP_TIMEOUT"
            )
        if last is not None:
            raise LLMError(f"model request failed after retries ({self.max_attempts} attempts): {last}")
        raise LLMError(f"model request failed after retries ({self.max_attempts} attempts)")


def build_llm(
    model: str = "mistral/codestral-2508",
    budget_usd: float = 1.0,
    dry_run: bool = False,
    budget_manager: BudgetManager | None = None,
    phase_c: bool = False,
    **kwargs,
) -> BaseLLM:
    if dry_run:
        return DryRunLLM(model=model)
    return HTTPLLM(
        model=model,
        budget_usd=budget_usd,
        budget_manager=budget_manager,
        phase_c=phase_c,
        **kwargs,
    )
