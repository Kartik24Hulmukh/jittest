"""Model access over urllib: Anthropic Messages and any OpenAI-compatible API.

litellm supports thousands of models and is a large dependency for two POSTs,
so it stays optional (JITTEST_USE_LITELLM=1). What earns its keep here: a hard
budget cap raised before the request is sent, an on-disk response cache, and
DryRunLLM, which runs the whole pipeline with no network and no key.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from ._litellm import LiteLLMBackend
from ._llmbase import BaseLLM, BudgetExceeded, LLMError, Usage
from ._llmcache import _Cache
from ._llmjson import extract_json, strip_code_fence
from ._pricing import PRICES, estimate_tokens, price_for


class RateLimitedError(LLMError):
    """Raised when the LLM provider rate limits requests after retries."""


class TimedOutError(LLMError):
    """Raised when the LLM provider times out on all retries."""


__all__ = [
    "LLMError", "RateLimitedError", "TimedOutError", "BudgetExceeded", "Usage",
    "BaseLLM", "HTTPLLM", "LiteLLMBackend", "DryRunLLM", "build_llm",
    "extract_json", "strip_code_fence", "PRICES", "price_for", "estimate_tokens",
]


_BASES = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}
_RETRYABLE = {408, 409, 429, 500, 502, 503, 529}
_RATE_LIMITED = {429, 503}

# Free-tier endpoints rate limit on a rolling window that is usually a minute
# wide. The previous policy was five attempts backing off 1+2+4+8+16 seconds,
# which exhausts itself in about half that window and then reports failure. A
# run that dies there records `not_measured` with no cause, which is
# indistinguishable from the tool having had nothing to say. Waiting is free;
# an unmeasured run is not.
_DEFAULT_MAX_ATTEMPTS = 8
_DEFAULT_MAX_SLEEP = 90.0
_RATE_LIMIT_FLOOR = 5.0

# Reasoning models bill and spend time on a trace before the first content
# token appears. 180s was chosen when every supported model answered directly;
# on a large diff a model that always reasons can exceed it, and a read timeout
# used to end the request outright. Waiting longer is cheaper than an
# unmeasured bug.
_DEFAULT_HTTP_TIMEOUT = 300.0


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


def retry_after_seconds(exc: urllib.error.HTTPError) -> float | None:
    """Seconds the server asked us to wait, or None if it did not say.

    RFC 9110 permits either a delay in seconds or an HTTP-date. Reading this is
    the difference between backing off for the window the provider actually
    enforces and guessing at a power of two. Malformed values return None
    rather than raising: a broken header is a reason to fall back, not to lose
    the run.
    """
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


class DryRunLLM(BaseLLM):
    """A model-shaped object that costs nothing and needs no network. Not a
    toy: it is how the pipeline is tested end to end before any key exists."""

    DEFAULT = (
        "# NO_CANDIDATE  (dry run: no model was called)" + chr(10)
    )

    def __init__(self, scripted: list[str] | None = None, model: str = "dry-run"):
        super().__init__(model, budget_usd=0.0, temperature=0.0)
        self.scripted = list(scripted or [])
        self.calls: list[tuple[str, str]] = []
        self._i = 0

    def complete(self, system: str, user: str, n: int = 1,
                 temperature: float | None = None) -> list[str]:
        self.calls.append((system, user))
        self.usage.calls += 1
        if self._i < len(self.scripted):
            reply = self.scripted[self._i]
            self._i += 1
        else:
            reply = self.scripted[-1] if self.scripted else self.DEFAULT
        return [reply] * max(1, n)


class HTTPLLM(BaseLLM):
    def __init__(self, model: str, api_key: str | None = None,
                 budget_usd: float = 1.0, temperature: float = 0.8,
                 cache_path: Path | str | None = None,
                 request_ceiling: int | None = None,
                 min_request_interval: float | None = None,
                 http_timeout: float | None = None):
        super().__init__(model, budget_usd, temperature)
        provider, _, name = model.partition("/")
        if not name:
            provider, name = ("anthropic" if "claude" in model else "openai"), model
        self.provider = provider
        self.model_name = name
        # With an explicit API base (e.g. NVIDIA NIM) the full namespaced model
        # id must reach the provider; built-in providers keep the bare name.
        self.api_key = api_key or self._find_key(provider)
        explicit_base = os.getenv("JITTEST_API_BASE")
        self.base_url = explicit_base or _BASES.get(
            provider, "https://api.anthropic.com/v1")
        self.api_model = model if explicit_base else self.model_name
        self.cache = _Cache(cache_path)
        self.request_ceiling = request_ceiling
        self.max_attempts = _env_int("JITTEST_MAX_RETRIES", _DEFAULT_MAX_ATTEMPTS)
        self.max_sleep = _env_float("JITTEST_RETRY_MAX_SLEEP", _DEFAULT_MAX_SLEEP)
        if min_request_interval is None:
            min_request_interval = _env_float("JITTEST_MIN_REQUEST_INTERVAL", 0.0)
        self.min_request_interval = min_request_interval
        if http_timeout is None:
            http_timeout = _env_float("JITTEST_HTTP_TIMEOUT", _DEFAULT_HTTP_TIMEOUT)
        self.http_timeout = http_timeout or _DEFAULT_HTTP_TIMEOUT
        self._last_request_at: float | None = None
        self.rate_limit_waits = 0
        self.rate_limit_seconds = 0.0
        self.timeout_retries = 0
        self._unpriced = self._price() is None
        if self._unpriced:
            import sys
            print(f"  warning: pricing is unknown for model '{model}'. "
                  f"A request-count ceiling will be enforced instead of a "
                  f"dollar cap.", file=sys.stderr)
        if not self.api_key and provider != "ollama":
            raise LLMError(
                "no API key found. Set JITTEST_API_KEY, or run with --dry-run.")

    @staticmethod
    def _find_key(provider: str) -> str | None:
        for name in ("JITTEST_API_KEY", f"{provider.upper()}_API_KEY",
                     "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            if os.getenv(name):
                return os.environ[name]
        return None

    def _price(self) -> tuple[float, float] | None:
        return price_for(self.model_name) or price_for(self.model)

    def _account(self, input_tokens: int, output_tokens: int,
                 estimated: bool = False) -> None:
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

    def _account_response(self, reported_in, reported_out,
                          prompt: str, text: str) -> None:
        """Account one response, estimating tokens only when none were given.
        Gateways that omit `usage` would otherwise report a false $0.000 run
        and leave the budget guard with nothing to guard."""
        try:
            in_tokens = int(reported_in or 0)
            out_tokens = int(reported_out or 0)
        except (TypeError, ValueError):
            in_tokens = out_tokens = 0
        if in_tokens or out_tokens:
            self._account(in_tokens, out_tokens)
            return
        self._account(estimate_tokens(prompt), estimate_tokens(text),
                      estimated=True)

    def _sleep(self, seconds: float) -> None:
        """Indirection so tests can assert on waiting without doing any."""
        if seconds > 0:
            time.sleep(seconds)

    def _pace(self) -> None:
        """Hold a minimum gap between requests.

        Retrying after a 429 is recovery. Not provoking one is prevention, and
        on a requests-per-minute quota prevention is the cheaper of the two.
        """
        if self.min_request_interval <= 0 or self._last_request_at is None:
            return
        gap = self.min_request_interval - (time.monotonic() - self._last_request_at)
        if gap > 0:
            self._sleep(gap)

    def _backoff(self, attempt: int, requested: float | None,
                 rate_limited: bool) -> float:
        if requested is not None:
            return min(requested, self.max_sleep)
        base = 2.0 ** attempt
        if rate_limited:
            base = max(base, _RATE_LIMIT_FLOOR)
        # Full jitter. Identical clients retrying on identical boundaries is
        # how one 429 becomes a stampede of them.
        return random.uniform(0.0, min(base, self.max_sleep))

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        last_code: int | None = None
        for attempt in range(self.max_attempts):
            requested: float | None = None
            self._pace()
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            self._last_request_at = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=self.http_timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last, last_code = exc, exc.code
                if exc.code not in _RETRYABLE:
                    detail = exc.read().decode("utf-8", "ignore")[:400]
                    raise LLMError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
                if exc.code in _RATE_LIMITED:
                    requested = retry_after_seconds(exc)
            except TimeoutError as exc:
                # urlopen raises this bare for a read timeout. It is a sibling
                # of URLError, not a subclass, so it used to escape the loop
                # entirely and end the run on the first slow response.
                last, last_code = exc, None
                self.timeout_retries += 1
            except urllib.error.URLError as exc:
                last, last_code = exc, None
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
                f"({self.rate_limit_waits} waits, "
                f"{self.rate_limit_seconds:.1f}s slept). Pace requests with "
                f"JITTEST_MIN_REQUEST_INTERVAL, or wait longer with "
                f"JITTEST_MAX_RETRIES / JITTEST_RETRY_MAX_SLEEP.")
        if isinstance(last, TimeoutError):
            raise TimedOutError(
                f"{self.provider} did not answer within {self.http_timeout:.0f}s on "
                f"any of {self.max_attempts} attempts ({self.timeout_retries} read "
                f"timeouts). Models that always emit a reasoning trace are slow on "
                f"large diffs; raise JITTEST_HTTP_TIMEOUT.")
        raise LLMError(f"model request failed after retries: {last}")

    def complete(self, system: str, user: str, n: int = 1,
                 temperature: float | None = None) -> list[str]:
        if self._unpriced:
            # max_targets * candidates_per_target + assessor calls (worst case)
            ceiling = self.request_ceiling
            if ceiling is None:
                ceiling = (int(os.getenv("JITTEST_MAX_TARGETS", "5")) *
                           int(os.getenv("JITTEST_CANDIDATES", "4")) + 5)
            self._guard_request_ceiling(ceiling)
        else:
            self._guard_budget()
        temp = self.temperature if temperature is None else temperature
        key = hashlib.sha256(
            f"{self.provider}|{self.model_name}|{system}|{user}|{n}|{temp}"
            .encode()).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            return json.loads(cached)

        outputs: list[str] = []
        for _ in range(max(1, n)):
            if self.provider == "anthropic":
                body = self._post(
                    f"{self.base_url}/messages",
                    {"model": self.model_name, "max_tokens": 2048,
                     "temperature": temp, "system": system,
                     "messages": [{"role": "user", "content": user}]},
                    {"content-type": "application/json",
                     "x-api-key": self.api_key or "",
                     "anthropic-version": "2023-06-01"},
                )
                text = "".join(
                    b.get("text", "") for b in body.get("content", [])
                    if b.get("type") == "text")
                usage = body.get("usage", {})
                self._account_response(usage.get("input_tokens"),
                                       usage.get("output_tokens"),
                                       system + user, text)
            else:
                body = self._post(
                    f"{self.base_url}/chat/completions",
                    {"model": self.api_model, "temperature": temp,
                     "max_tokens": 2048,
                     "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}]},
                    {"content-type": "application/json",
                     "authorization": f"Bearer {self.api_key or ''}"},
                )
                choices = body.get("choices", [])
                text = choices[0]["message"]["content"] if choices else ""
                usage = body.get("usage", {})
                self._account_response(usage.get("prompt_tokens"),
                                       usage.get("completion_tokens"),
                                       system + user, text)
            outputs.append(text or "")

        self.cache.put(key, json.dumps(outputs))
        return outputs


def build_llm(model: str, dry_run: bool = False, budget_usd: float = 1.0,
              temperature: float = 0.8, cache_path: Path | str | None = None,
              api_key: str | None = None,
              request_ceiling: int | None = None,
              min_request_interval: float | None = None,
              http_timeout: float | None = None) -> BaseLLM:
    if dry_run:
        return DryRunLLM(model=f"{model} (dry run)")
    if os.getenv("JITTEST_USE_LITELLM") == "1":
        return LiteLLMBackend(model, budget_usd, temperature)
    return HTTPLLM(model, api_key=api_key, budget_usd=budget_usd,
                   temperature=temperature, cache_path=cache_path,
                   request_ceiling=request_ceiling,
                   min_request_interval=min_request_interval,
                   http_timeout=http_timeout)
