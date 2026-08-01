# The oracle-strength scanner

`jittest oracles` answers one question about a pull request, offline and for
free: **do the tests that arrived with this change assert anything?**

It is the cheapest useful thing jittest does. No model call, no API key, no
network, no dollar cost, no rate limit, and a deterministic verdict, which
means it can gate CI on the first day of adoption rather than after somebody
provisions a key.

## Why this exists

arXiv 2606.18168, *All Smoke, No Alarm: Oracle Signals in Agent-Authored Test
Code* (Banik, Chowdhury, Shamim, 16 June 2026), classified 86,156 cumulative
test-file patches from 33,596 agent-authored pull requests across 2,807
repositories with at least 100 stars. Findings relevant here:

- **80.2%** of agent-authored test patches carry a weak oracle or none at all.
- On newly created test files the strong-oracle rate ranges from **18%**
  (OpenAI Codex) to **67%** (Claude Code).
- A strong oracle significantly predicts merge after adjusting for agent, patch
  size, stars, task type and language: **adjusted OR 1.28, p < 0.001**.
- The paper's own recommendation is "oracle-aware CI checks that flag newly
  added test files lacking assertion patterns".

The population this applies to is not small: the AIDev dataset the study draws
from contains more than 932,000 agent-authored pull requests across more than
116,000 repositories.

## The taxonomy

| code | meaning | example |
| --- | --- | --- |
| W1 | no assertion at all | `result = f()` |
| W2 | existence or null check only | `assert result`, `assertIsNotNone(x)` |
| W3 | boolean-only | `assertTrue(f())`, `assert x is True` |
| W4 | mock verification only | `m.assert_called_once_with(3)` |
| W5 | snapshot comparison only | `assert page == snapshot` |
| S1 | value equality or ordering | `assert f(2) == 4`, `assertIn(a, b)` |
| S2 | error containment or type | `pytest.raises`, `assertIsInstance` |
| S3 | two or more strong signals | both of the above in one test |

A test is **strong** when its verdict starts with `S`.

## Usage

```bash
# every test file this branch changed, compared against main
jittest oracles --changed --base origin/main --head HEAD

# an explicit file or directory
jittest oracles tests/

# machine-readable
jittest oracles tests/ --json

# gate CI: fail when fewer than 60% of the scanned tests assert a value
jittest oracles --changed --fail-under 0.6

# write a PR comment body
jittest oracles --changed --markdown oracle.md
```

Exit codes: `0` clean, `1` the `--fail-under` gate was not met, `2` the scan
could not be performed at all.

## What it will not do

- **It does not claim a weak oracle is a bug.** A smoke test is a legitimate
  thing to write on purpose. The claim is narrower: a reviewer should be told,
  before merging, that the new test file asserts nothing about the value under
  test. A weak oracle should be a decision, not an accident.
- **It never emits your source code.** A finding carries a category, a symbol
  name and a line number. This is the same guarantee jittest asserts about its
  telemetry in `test_telemetry_never_contains_source_code`, and a parse failure
  is reported by exception type only because `SyntaxError.text` holds the
  offending line.
- **It does not report a rate for zero tests.** `strong_rate` is `null`, not
  `0.0`, when nothing was scanned. A rate of zero says every test is weak; a
  null says no test was seen. Conflating those two is the mistake that produced
  Defect 22 on this project.
- **It is a heuristic, and it is tuned to under-claim.** A bare `raises(...)`
  that is not `pytest.raises` is not credited, because guessing generously
  would inflate the one number this check exists to report honestly.

## Relationship to the catching-test pipeline

They answer different questions and neither replaces the other.

| | `jittest oracles` | `jittest run` |
| --- | --- | --- |
| question | do these tests assert anything? | does this change break something? |
| cost | $0.00 | model-priced per pull request |
| needs a key | no | yes |
| deterministic | yes | no |
| verdict | a classification | an executed base/head pair |
