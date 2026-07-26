# Quickstart

Five minutes. No API key needed for the first three steps.

## 1. Install

```bash
pip install jittest
```

No dependencies are pulled in. Python 3.11+ and `git` are the only requirements.

## 2. Check the environment

```bash
cd your-repo
jittest doctor
```

```
jittest 0.2.0 doctor
  [ok  ] python >= 3.11 - 3.13.1
  [ok  ] git available - git version 2.45.2
  [ok  ] inside a git repository - /home/you/your-repo
  [ok  ] test runner: pytest
  [warn] model API key present - only --dry-run will work
  [ok  ] model anthropic/claude-sonnet-4-5, budget $1.00, max targets 5
  [ok  ] ledger /home/you/your-repo/.jittest/ledger.db
  [ok  ] 15 ignore pattern(s)
```

## 3. Dry run — free, no key, no network

```bash
jittest run --base main --head HEAD --dry-run
```

This runs everything except the model: the diff parser, the risk ranker, both
git worktrees and the oracle. You will see which symbols jittest would have
spent money on, and why. If it is targeting the wrong things, tune
`risk_threshold` and `ignore` before you spend anything.

## 4. A real run

```bash
export JITTEST_API_KEY=sk-...
jittest run --base main --head HEAD --budget 0.50
```

```
jittest v0.2.0  0f9e8d7c...a1b2c3d4
  3 symbol(s) analysed | 7 candidate(s) | 1 catching | $0.214

  [REGRESSION] billing/calc.py::apply_discount
    Removing the clamp lets a discount above 100% return a negative price.
    oracle: catching: passes on base, fails on head
    reproduce: git checkout a1b2c3d4e5f6 && pytest billing/calc.py -q   # expect FAIL
```

A run that finds nothing is the common case and is not a failure. Most diffs do
not contain a regression.

## 5. Add it to CI

```yaml
name: jittest
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  catching-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: Kartik24Hulmukh/jittest@v0.2.0
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
          budget: "1.00"
          comment: "true"
        env:
          JITTEST_API_KEY: ${{ secrets.JITTEST_API_KEY }}
```

`fetch-depth: 0` matters: the oracle needs to check out both commits.

Start without `fail-on-regression`. Let it comment for a couple of weeks, label
the findings, then decide whether it has earned the right to block a merge.

## 6. Tell it when it was right or wrong

```bash
jittest stats
jittest outcome 9f3a2b7c1d0e4f58 fixed_code
jittest outcome 4c1e8a02b7d63f91 false_positive --note "assertion was on a private helper"
```

This is the highest-value thing you can do with two seconds. It is the only
honest measure of precision, and it is what a future risk model learns from.

## Tuning

| Symptom | Fix |
| --- | --- |
| Too expensive | lower `max_targets`, lower `candidates_per_target`, raise `risk_threshold`, or use a cheaper model |
| Targets the wrong files | add globs to `.jittestignore` |
| Never finds anything | lower `risk_threshold`, raise `candidates_per_target`, check `--dry-run` output for what is being targeted |
| Slow | lower `--timeout`, lower `--reruns` to 1 (at the cost of flakiness protection) |
| "could not be collected" everywhere | your package is probably not importable from the repo root; check `jittest doctor` and your `src/` layout |

## Uninstall cleanly

```bash
rm -rf .jittest/      # ledger and response cache, both local
pip uninstall jittest
```

Nothing leaves your machine except the model calls themselves.
