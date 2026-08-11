"""Oracle-Last Assertion Synthesizer for Phase D.

Synthesizes deterministic assertions ONLY AFTER observing a stable paired behavioral difference
between BASE and HEAD.
"""

from __future__ import annotations

import ast
import re
from jittest.phase_d.differential import PairedResult

VOLATILE_PATTERNS = [
    re.compile(r"0x[0-9a-fA-F]+"),  # Memory addresses
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),  # UUIDs
    re.compile(r"\b20[2-9][0-9]-[01][0-9]-[0-3][0-9]\b"),  # Dates YYYY-MM-DD
]


def contains_volatile_token(text: str) -> bool:
    for pattern in VOLATILE_PATTERNS:
        if pattern.search(text):
            return True
    return False


ORACLE_SYNTHESIS_SYSTEM = """You are a precise oracle synthesizer.
Your task is to take a probe test code that exhibited a stable behavioral difference between BASE and HEAD, and synthesize a deterministic assertion.

CRITICAL RULES:
1. Synthesize an assertion that PASSES on BASE and FAILS on HEAD.
2. Prohibit volatile memory addresses (0x...), UUIDs, timestamps, or non-deterministic ordering.
3. Return ONLY valid Python test code in a ```python block.
"""

ORACLE_SYNTHESIS_USER = """Probe Test Code:
```python
{code}
```

Observed Paired Difference:
- BASE Outcome: {base_outcome} (Return: {base_return})
- HEAD Outcome: {head_outcome} (Return: {head_return}, Exception: {head_exception})

Synthesize the final deterministic test function with exact assertions.
"""


class OracleLastSynthesizer:
    def is_valid_oracle_code(self, code: str) -> bool:
        if contains_volatile_token(code):
            return False
        try:
            tree = ast.parse(code)
            has_assertion = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Assert):
                    has_assertion = True
                elif isinstance(node, ast.With):
                    for item in node.items:
                        expr = ast.unparse(item.context_expr)
                        if "raises" in expr:
                            has_assertion = True
                elif isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    elif isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    if func_name.startswith("assert") and func_name != "assert":
                        has_assertion = True
            return has_assertion
        except Exception:
            return False
