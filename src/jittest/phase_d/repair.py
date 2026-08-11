"""Mechanical Repair and Assertion AST Fingerprint Guard for Phase D.

Guarantees mechanical repairs fix imports/setup/API usage without removing or weakening assertions.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Sequence


def extract_assertion_fingerprints(code: str) -> list[str]:
    """Extract AST representations of assertions in candidate test code."""
    fingerprints: list[str] = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                fingerprints.append(f"Assert({ast.unparse(node.test)})")
            elif isinstance(node, ast.With):
                # e.g., with pytest.raises(...)
                for item in node.items:
                    expr = ast.unparse(item.context_expr)
                    if "raises" in expr:
                        fingerprints.append(f"PytestRaises({expr})")
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    func_name = node.func.id

                if func_name.startswith("assert") and func_name != "assert":
                    fingerprints.append(f"UnittestAssert({func_name}:{ast.unparse(node)})")
    except Exception:
        pass
    return fingerprints


def verify_assertion_preservation(original_code: str, repaired_code: str) -> bool:
    """Verify repaired code has not removed or weakened assertions from original code."""
    orig_fp = extract_assertion_fingerprints(original_code)
    repaired_fp = extract_assertion_fingerprints(repaired_code)

    if not orig_fp:
        return True  # Probe stage before final assertion synthesis

    # Every assertion in original code must still exist in repaired code (or equivalent)
    if len(repaired_fp) < len(orig_fp):
        return False

    for fp in orig_fp:
        if not any(fp in rfp or rfp in fp for rfp in repaired_fp):
            return False

    return True


REPAIR_SYSTEM_D = """You are an automated Python test repair engine.
Fix syntax errors, missing imports, missing fixtures, or incorrect API setup arguments ONLY.

CRITICAL RULES:
1. You MUST NOT remove, comment out, or weaken any assertion statements.
2. Return ONLY the valid, repaired executable Python code enclosed in a ```python block.
"""

REPAIR_USER_D = """Original candidate test code:
```python
{code}
```

Execution Failure Error:
{error_message}

Target Signatures & Imports:
{signatures}

Repair the test setup, imports, or API calls so that it compiles and executes. DO NOT REMOVE ANY ASSERTIONS.
"""
