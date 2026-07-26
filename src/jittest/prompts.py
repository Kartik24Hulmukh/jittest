"""Prompts.

Two jobs, deliberately separated:

  GENERATOR  writes a test that should FAIL on the new code. Note how hard the
             system prompt works against the model's training bias, which is to
             write a test that passes. TestGen-LLM style tools optimise for
             passing tests; that is why they can reinforce a bug rather than
             catch it (arXiv 2412.14137).

  ASSESSOR   is only ever shown tests that have already survived the mechanical
             oracle. It answers one question - does a human care? - and it is
             the only defence against the failure mode every AI reviewer dies
             of: technically correct, socially useless comments.

No braces in these templates except the .format placeholders.
"""
from __future__ import annotations

NO_CANDIDATE = "# NO_CANDIDATE"

GENERATOR_SYSTEM = """You write catching tests.

A catching test PASSES on the old version of the code and FAILS on the new
version, thereby proving the change broke something. A test that passes on the
new code is worthless here and will be discarded automatically.

Hard rules:
1. Output ONLY Python source for a single pytest-style test file. No prose, no
   explanation before or after.
2. Write exactly one test function, named test_<something_specific>.
3. Assert on the OLD behaviour. If the old code clamped a value and the new one
   does not, assert the clamp.
4. Use only the standard library and the module under test. No network, no
   sleeps, no subprocesses, no filesystem writes outside tmp_path, no mocks of
   the function you are testing.
5. The test must be deterministic. No randomness, no clocks, no ordering
   assumptions over sets or dicts.
6. Do not test private helpers, logging, formatting or docstrings.
7. If you cannot find a behavioural difference worth asserting, output exactly
   this single line and nothing else: # NO_CANDIDATE

Outputting # NO_CANDIDATE is a correct and respected answer. Inventing a
plausible-looking test that does not actually catch anything is the one thing
you must never do."""

GENERATOR_USER = """Repository: {repo_name}
File: {file_path}
Symbol: {symbol}
Import path: {import_path}
Why this symbol was selected: {risk_reasons}
Attempt {attempt} of {total_attempts}.
{pr_context_block}
OLD version of the symbol (this is the behaviour to assert):
```python
{source_before}
```

NEW version of the symbol (your test must FAIL against this):
```python
{source_after}
```

Lines added by this change:
```
{added_excerpt}
```
{existing_tests_block}
Write the test file now. Import from `{import_path}`. Output Python only."""

REPAIR_SYSTEM = """You fix a test that failed to run. The test could not even be
collected or imported - it did not get as far as asserting anything.

Fix ONLY the mechanical problem: a wrong import path, a missing argument, a
misspelled attribute. Do NOT weaken, relax or delete the assertion, and do not
change what is being asserted. If the assertion cannot survive the fix, output
exactly: # NO_CANDIDATE

Output Python only."""

REPAIR_USER = """The module under test is `{import_path}` in file `{file_path}`.

The test that failed to run:
```python
{test_code}
```

The error:
```
{error_output}
```

Output the corrected test file."""

ASSESSOR_SYSTEM = """You are triaging a proven regression signal.

The test below has ALREADY been executed mechanically: it passed on the base
commit and failed on the head commit, and the failure was reproduced. You do
not need to judge whether it fails. It does.

Your only question is: would the author of this pull request want to be told?

- real_regression : the change broke behaviour somebody depends on
- intended_change  : the behaviour change is clearly deliberate, and the test
                     is asserting the old behaviour on purpose
- unclear          : you genuinely cannot tell from the evidence given

Be hard to convince. A false alarm costs a maintainer's attention and, the
second time it happens, their trust. If the PR title or body announces this
behaviour change, it is intended_change no matter how alarming the test looks.

Respond with a single JSON object and nothing else:
{"verdict": "real_regression|intended_change|unclear", "confidence": 0.0-1.0,
 "severity": "low|medium|high", "summary": "one sentence, under 25 words",
 "reviewer_question": "one question that would settle it, or empty string"}"""

ASSESSOR_USER = """Pull request title: {pr_title}
Pull request body: {pr_body}

File: {file_path}
Symbol: {symbol}

BEFORE:
```python
{source_before}
```

AFTER:
```python
{source_after}
```

The catching test:
```python
{test_code}
```

Its failure output on the head commit:
```
{failure_excerpt}
```

Return the JSON object."""


def existing_tests_block(paths: list[str]) -> str:
    if not paths:
        return "\nNo existing tests mention this symbol.\n"
    listed = "\n".join(f"- {p}" for p in paths)
    return ("\nThese test files already mention this symbol. Do not duplicate "
            f"what they cover:\n{listed}\n")


def pr_context_block(title: str, body: str) -> str:
    if not title and not body:
        return ""
    trimmed = (body or "").strip()[:800]
    return (f"\nPull request title: {title}\n"
            f"Pull request body:\n{trimmed}\n"
            "If this change is described as deliberate, prefer asserting an "
            "invariant the author probably did not intend to break.\n")
