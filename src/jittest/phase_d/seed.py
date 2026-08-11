"""Seed-First Generator for Phase D Differential Explorer.

Discovers existing repository tests reaching target_symbol, verifies passing behavior
on BASE, and generates input-mutation probe tasks.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass
class SeedCandidate:
    test_file: str
    test_name: str
    code: str
    passes_on_base: bool = False
    source_category: str = "raw_generated"  # "seed_mutated" or "raw_generated"


class SeedFinder:
    def __init__(self, repo_path: Path):
        self.repo_path = Path(repo_path)

    def find_seed_tests(self, target_symbol: str, target_file: str) -> list[SeedCandidate]:
        """Find candidate seed tests in the repo referencing target_symbol."""
        base_name = target_symbol.split(".")[-1]
        seeds: list[SeedCandidate] = []

        test_files = list(self.repo_path.glob("**/test_*.py")) + list(self.repo_path.glob("**/*_test.py"))
        for tf in test_files:
            try:
                content = tf.read_text(encoding="utf-8", errors="ignore")
                if base_name not in content and target_symbol not in content:
                    continue

                tree = ast.parse(content, filename=str(tf))
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name.startswith("test_") or node.name.endswith("_test"):
                            fn_source = ast.get_source_segment(content, node)
                            if fn_source and (base_name in fn_source or target_symbol in fn_source):
                                rel_file = str(tf.relative_to(self.repo_path)).replace("\\", "/")
                                seeds.append(
                                    SeedCandidate(
                                        test_file=rel_file,
                                        test_name=node.name,
                                        code=fn_source,
                                        passes_on_base=False,
                                        source_category="seed_mutated",
                                    )
                                )
            except Exception:
                continue

        return seeds

    def format_seed_probe_prompt(self, seed: SeedCandidate, context_text: str) -> str:
        return f"""You are a differential test generator in Seed-First mode.

Existing passing repository seed test (`{seed.test_name}` in `{seed.test_file}`):
```python
{seed.code}
```

Target context & code differences:
{context_text}

Task: Mutate the input values, parameters, setup, or execution arguments of the seed test to probe edge cases and expose behavioral differences in the target between BASE and HEAD.

Requirements:
- Preserve valid imports and fixtures from the seed test.
- Write a clean standalone test function beginning with `def test_`.
- Do not write fragile assertions yet; write probe statements that execute the target under varied inputs.
"""
