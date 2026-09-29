"""Refuse to start a funded sweep against a model the endpoint no longer serves.

Receipt: eval run 36346472249. vars.JITTEST_MODEL pointed at a model that had
reached end of life on the provider (HTTP 410 Gone). The workflow cloned
BugsInPy, installed three projects and asked the dead model for every
candidate before anyone could see why nothing was measured. Listing the
provider catalogue costs nothing and answers that question in one second.

Exit codes: 0 model is served (or the catalogue cannot be listed, which is
reported as a warning, not guessed at), 1 model is not in the catalogue.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from jittest.llm import LLMError, build_llm


def served_models(api_base: str, api_key: str, timeout: float = 20.0) -> list[str] | None:
    req = urllib.request.Request(
        api_base.rstrip("/") + "/models",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"::warning::could not list models at {api_base}: {exc}", file=sys.stderr)
        return None
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    return [str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")]


def check(model: str, catalogue: list[str] | None) -> tuple[bool, str]:
    if catalogue is None:
        return True, "catalogue unavailable; model not verified"
    if model in catalogue:
        return True, f"model {model} is served"
    vendor = model.split("/", 1)[0] + "/"
    near = sorted(m for m in catalogue if m.startswith(vendor))
    hint = f" Served by the same vendor: {', '.join(near)}." if near else ""
    return False, (f"model {model} is not served by this endpoint (retired or "
                   f"misspelt). Set vars.JITTEST_MODEL or the model input.{hint}")


def preflight_model(model: str, budget: float = 0.05) -> dict:
    llm = build_llm(model, budget_usd=budget, request_ceiling=1, http_timeout=15)
    if llm._price() is None:
        raise LLMError("model unpriced: set JITTEST_MODEL_PRICE or JITTEST_EUR_USD before paid evaluation")
    llm.max_attempts = 1
    outputs = llm.complete("Reply briefly.", "Reply only OK", temperature=0)
    if not outputs or not outputs[0].strip():
        raise LLMError("preflight returned empty content")
    return {"model": model, "status": "responsive", "cost_usd": llm.usage.cost_usd,
            "input_tokens": llm.usage.input_tokens, "output_tokens": llm.usage.output_tokens,
            "tokens_estimated": llm.usage.tokens_estimated,
            "provider_billing": llm.usage.provider_billing}



def main() -> int:
    model = os.environ.get("JITTEST_MODEL", "")
    base = os.environ.get("JITTEST_API_BASE", "")
    key = os.environ.get("JITTEST_API_KEY", "")
    if not (model and base and key):
        print("ERROR: JITTEST_MODEL, JITTEST_API_BASE and JITTEST_API_KEY are required")
        return 1
    ok, msg = check(model, served_models(base, key))
    print(("" if ok else "ERROR: ") + msg)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
