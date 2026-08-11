"""Robust JSON extraction from model replies.

Kept apart from transport: the parser is the piece most likely to be attacked
by a model's prose, so it is the piece most worth testing in isolation.
"""
from __future__ import annotations

import json

__all__ = ["strip_code_fence", "extract_json"]


def strip_code_fence(text: str) -> str:
    body = (text or "").strip()
    if "```" in body:
        parts = body.split("```")
        if len(parts) >= 3:
            code_block = parts[1]
            lines = code_block.splitlines()
            if lines and lines[0].strip().lower() in ("python", "py"):
                lines = lines[1:]
            return "\n".join(lines).strip()
    if body.startswith("```"):
        lines = body.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return body


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
            elif ch == chr(92):
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
