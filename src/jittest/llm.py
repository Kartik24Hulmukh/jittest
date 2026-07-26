"""Model access over urllib. Anthropic Messages and any OpenAI-compatible API.

litellm is excellent and supports thousands of models; it is also a large
dependency tree to inject into somebody else's CI for what amounts to two POST
requests. So it is optional: set JITTEST_USE_LITELLM=1 and it is used instead.

Three things here earn their keep:
  - a hard budget cap that raises before the request is sent, not after
  - an on-disk response cache, so re-running a PR costs nothing
  - DryRunLLM, which lets the entire pipeline (and its test suite) run with no
    network and no key at all
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "LLMError", "BudgetExceeded", "Usage", "BaseLLM", "HTTPLLM", "LiteLLMBackend",
    "DryRunLLM", "build_llm", "extract_json", "strip_code_fence", "PRICES",
]


class LLMError(RuntimeError):
    pass


class BudgetExceeded(LLMError):
    pass


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
}

_BASES = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "together": "https://api.together.xyz/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "ollama": "http://localhost:11434/v1",
}
_RETRYABLE = {408, 409, 429, 500, 502, 503, 529}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    cost_usd: float = 0.0
    priced: bool = True


def strip_code_fence(text: str) -> str:
    body = (text or "").strip()
    if not body.startswith("```"):
        return body
    lines = body.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json(text: str) -> dict | None:
    """Find the first balanced JSON object, ignoring prose and code fences.

    Models add pleasantries. `json.loads` on the whole response is a bug.
    """
    if not text:
        return None
    body = strip_code_fence(text)
    try:
        parsed = json.loads(body)
        return parsed if isinstance(parsed, dict) else None
    except ValueError:
        pass

    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(body[start:i + 1])
                    if isinstance(parsed, dict):
                        return parsed
                except ValueError:
                    start = -1
    return None


class _Cache:
    def __init__(self, path: Path | str | None) -> None:
        self.conn = None
        if not path:
            return
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(p))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, at REAL)")
        self.conn.commit()

    def get(self, key: str) -> str | None:
        if not self.conn:
            return None
        row = self.conn.execute("SELECT v FROM cache WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def put(self, key: str, value: str) -> None:
        if not self.conn:
            return
        self.conn.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                          (key, value, time.time()))
        self.conn.commit()


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


class DryRunLLM(BaseLLM):
    """A model-shaped object that costs nothing and needs no network.

    This is not a toy. It is how the pipeline is tested end to end, and how a
    new user can watch jittest work on their own repository before deciding
    whether to hand it an API key.
    """

    DEFAULT = (
        "# NO_CANDIDATE  (dry run: no model was called)\n"
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
                 cache_path: Path | str | None = None):
        super().__init__(model, budget_usd, temperature)
        provider, _, name = model.partition("/")
        if not name:
            provider, name = ("anthropic" if "claude" in model else "openai"), model
        self.provider = provider
        self.model_name = name
        self.api_key = api_key or self._find_key(provider)
        self.base_url = os.getenv("JITTEST_API_BASE") or _BASES.get(
            provider, "https://api.anthropic.com/v1")
        self.cache = _Cache(cache_path)
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
        for key, price in PRICES.items():
            if key in self.model_name:
                return price
        return None

    def _account(self, input_tokens: int, output_tokens: int) -> None:
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.usage.calls += 1
        price = self._price()
        if price is None:
            self.usage.priced = False
            return
        self.usage.cost_usd += (input_tokens * price[0] + output_tokens * price[1]) / 1e6

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        for attempt in range(5):
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in _RETRYABLE:
                    detail = exc.read().decode("utf-8", "ignore")[:400]
                    raise LLMError(f"HTTP {exc.code} from {self.provider}: {detail}") from exc
            except urllib.error.URLError as exc:
                last = exc
            time.sleep(min(30.0, 2.0 ** attempt))
        raise LLMError(f"model request failed after retries: {last}")

    def complete(self, system: str, user: str, n: int = 1,
                 temperature: float | None = None) -> list[str]:
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
                self._account(usage.get("input_tokens", 0), usage.get("output_tokens", 0))
            else:
                body = self._post(
                    f"{self.base_url}/chat/completions",
                    {"model": self.model_name, "temperature": temp,
                     "max_tokens": 2048,
                     "messages": [{"role": "system", "content": system},
                                  {"role": "user", "content": user}]},
                    {"content-type": "application/json",
                     "authorization": f"Bearer {self.api_key or ''}"},
                )
                choices = body.get("choices", [])
                text = choices[0]["message"]["content"] if choices else ""
                usage = body.get("usage", {})
                self._account(usage.get("prompt_tokens", 0),
                              usage.get("completion_tokens", 0))
            outputs.append(text or "")

        self.cache.put(key, json.dumps(outputs))
        return outputs


class LiteLLMBackend(BaseLLM):
    """Optional: `pip install jittest[litellm]` for 2900+ providers."""

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


def build_llm(model: str, dry_run: bool = False, budget_usd: float = 1.0,
              temperature: float = 0.8, cache_path: Path | str | None = None,
              api_key: str | None = None) -> BaseLLM:
    if dry_run:
        return DryRunLLM(model=f"{model} (dry run)")
    if os.getenv("JITTEST_USE_LITELLM") == "1":
        return LiteLLMBackend(model, budget_usd, temperature)
    return HTTPLLM(model, api_key=api_key, budget_usd=budget_usd,
                   temperature=temperature, cache_path=cache_path)
