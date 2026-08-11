"""Differential Explorer for Phase D.

Manages paired BASE and HEAD execution, coverage feedback, reachability analysis,
and differential mutation prompts.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExecutionTrace:
    outcome: str  # "PASS", "FAIL_SETUP", "FAIL_ASSERT", "FAIL_EXCEPTION"
    return_value_repr: str = ""
    exception_type: str = ""
    exception_message: str = ""
    target_reached: bool = False
    covered_changed_lines: list[int] = field(default_factory=list)
    stderr: str = ""
    stdout: str = ""

    def normalized_signature(self) -> str:
        if self.outcome == "PASS":
            return f"PASS:{self.return_value_repr}"
        return f"FAIL:{self.exception_type}:{self.exception_message}"


@dataclass
class PairedResult:
    candidate_sha: str
    base_trace: ExecutionTrace
    head_trace: ExecutionTrace
    is_identical: bool = False
    has_paired_difference: bool = False

    def __post_init__(self):
        self.is_identical = self.base_trace.normalized_signature() == self.head_trace.normalized_signature()
        self.has_paired_difference = (
            self.base_trace.outcome == "PASS"
            and self.head_trace.outcome in ("FAIL_ASSERT", "FAIL_EXCEPTION")
        ) or (
            self.base_trace.outcome == "PASS"
            and self.head_trace.outcome == "PASS"
            and self.base_trace.return_value_repr != self.head_trace.return_value_repr
        )


class DifferentialExplorer:
    def __init__(self):
        self.seen_shas: set[str] = set()

    def compute_sha(self, code: str) -> str:
        return hashlib.sha256(code.encode("utf-8")).hexdigest()

    def is_duplicate(self, code: str) -> bool:
        sha = self.compute_sha(code)
        if sha in self.seen_shas:
            return True
        self.seen_shas.add(sha)
        return False

    def format_differential_mutation_prompt(
        self,
        candidate_code: str,
        paired_result: PairedResult,
        context_text: str,
    ) -> str:
        return f"""You are a differential test generator in Differential Explorer mode.

Current probe test code:
```python
{candidate_code}
```

Paired Execution Observations:
- BASE Outcome: {paired_result.base_trace.outcome} (Output/Return: {paired_result.base_trace.return_value_repr}, Exception: {paired_result.base_trace.exception_type}: {paired_result.base_trace.exception_message})
- HEAD Outcome: {paired_result.head_trace.outcome} (Output/Return: {paired_result.head_trace.return_value_repr}, Exception: {paired_result.head_trace.exception_type}: {paired_result.head_trace.exception_message})
- Target Reached: BASE={paired_result.base_trace.target_reached}, HEAD={paired_result.head_trace.target_reached}
- Covered Changed Lines: {paired_result.head_trace.covered_changed_lines}

Observation: Both BASE and HEAD produced identical results ({paired_result.base_trace.normalized_signature()}).

Task: Mutate the input values or call sequence to reach unexercised branches in the target diff and force a behavioral divergence between BASE and HEAD.

Target context:
{context_text}

Requirements:
- Output a single standalone Python test function beginning with `def test_`.
"""
