# Dispatching the measurement run

The three numbers in `README.md` — catch rate, false-positive rate, cost per
analysed pull request — do not exist yet. `CHANGELOG.md` says so under **Still
not fixed**, and it is the correct thing to say. This file is the runbook for
the run that produces them.

The run costs real money and takes hours. Read this before dispatching, because
the first attempt is the cheapest one.

## Before dispatching: four defects in eval.yml

These were found by reading `.github/workflows/eval.yml` against the actual
argument parsers in `eval/run_bugsinpy.py` and `eval/false_positives.py`. Each
would have wasted a funded run. **They are not yet fixed** — see "Applying the
fix" below.

### 1. `timeout-minutes: 30` cannot finish a real sweep

The job clones BugsInPy, then per bug creates two git worktrees, installs that
project's dependencies and runs its test suite twice. At `limit: 40` this does
not complete in thirty minutes. The failure mode is the dangerous one: the job
is cancelled mid-sweep and leaves a partial `results.json`, which is
indistinguishable from a genuinely poor catch rate.

**Required:** `timeout-minutes: 240`.

### 2. `--budget` is never passed, and defaults to 1.0 USD

`run_bugsinpy.py` declares `--budget` with `default=1.0`. The workflow never
passes it. `eval/README.md` estimates roughly 0.50 USD per bug, so dispatching
with `limit: 40` against an unstated 1.00 USD ceiling stops the sweep after
approximately two bugs.

This is the single most expensive defect here, because it does not error. It
produces a small, real-looking catch rate computed over two bugs. If that
number were published it would be wrong in the direction that destroys
credibility.

**Required:** expose `budget` as a dispatch input and pass it through. For a
40-bug sweep, set it to at least `25.0`.

### 3. `report_suppressed` is a control that does nothing

The workflow declares a `report_suppressed` input. `run_bugsinpy.py` has no
such flag — its parser accepts only `--bugsinpy`, `--workdir`, `--limit`,
`--model`, `--budget`, `--out`, `--dry-run` and `--project`. The input is
silently discarded.

A control that appears to work and does nothing is worse than a missing
control, because the operator records a setting that was never applied. For a
project whose entire thesis is that model verdicts must be replaced by
mechanical evidence, an unwired dial in the measurement harness is the wrong
kind of irony.

**Required:** remove the input, or wire it to a real flag.

### 4. A missing key is discovered late

Credentials are read at the model step, after the BugsInPy clone and the pin
verification. A run with an empty `JITTEST_API_KEY` therefore spends several
minutes before failing, in a log that reads like a tool defect rather than a
configuration error.

**Required:** a preflight step that fails within seconds and names which of
`secrets.JITTEST_API_KEY`, `vars.JITTEST_MODEL` or `vars.JITTEST_API_BASE` is
absent.

### Also missing: the false-positive rate is not wired at all

`eval/false_positives.py` exists and is never invoked by any workflow.
`eval/README.md` states plainly that publishing the catch rate without the
false-positive rate is marketing, and that Meta's contribution in
[arXiv:2601.22832](https://arxiv.org/abs/2601.22832) was a ~70% reduction in
review load — a precision result, not a recall result. Both numbers should come
from one dispatch so they cannot drift apart.

`false_positives.py` accepts `--repo` (a local path, required), `--count`,
`--model` and `--budget`. A second job needs to clone a repository with
ordinary, unseeded history and point `--repo` at it.

## Applying the fix

Writing to `.github/workflows/` requires the `workflow` OAuth scope. An
integration without it receives:

```
403 Resource not accessible by integration
```

on both `PUT /repos/{owner}/{repo}/contents/.github/workflows/eval.yml` and
`POST /repos/{owner}/{repo}/git/trees`. This is the same 403 recorded earlier
against the false-positive CI wiring. It is a token scope limit, not a
repository permission problem, and it cannot be worked around from an
integration — it needs a commit from a human account or a token carrying the
`workflow` scope.

## Repository configuration required once

| Kind | Name | Where |
|---|---|---|
| Secret | `JITTEST_API_KEY` | Settings → Secrets and variables → Actions → Secrets |
| Variable | `JITTEST_MODEL` | Settings → Secrets and variables → Actions → Variables |
| Variable | `JITTEST_API_BASE` | same |

Never paste the key into a workflow file, a dispatch input, an issue, or a
commit. Dispatch inputs are recorded in the run metadata in plaintext.

## Dispatch sequence

1. **Smoke first.** `limit: 3`, `budget: 2.0`. Confirm the run reaches the
   assessor and that `assert_measured.py` passes. Cost: about 1.50 USD. Do not
   skip this — it is the cheapest possible test of the whole path.
2. **Read the artifact,** not the summary. Confirm `results.json` contains
   per-bug rows with real dispositions, and that `bugs_eligible` and
   `bugs_git_failed` are populated.
3. **Full sweep.** `limit: 40`, `budget: 25.0`. Expect hours.
4. **Write `eval/RESULTS.md`** with: catch rate over eligible bugs, the
   conservative `catch_rate_all_attempted` beside it, the false-positive rate,
   cost per analysed diff, the exact dispatch inputs, the BugsInPy pin
   `11c5f1eea954a42132cfd06bf257766a7963e0fd`, and a limitations section longer
   than the results section.

## Two things that must be in the limitations section

**Data leakage.** BugsInPy is public and appears in training corpora, so the
fixes may be memorised. `eval/README.md` already requires that headline claims
cite the lower of BugsInPy and a recent-bug set. GitBug-Java and the
project's own `git log --merges --grep=revert` history are the honest
comparisons.

**Seeded regressions are not caught bugs.** Two mechanical oracle catches
against seeded regressions in `Ledgermatch` and `AccessDoc` demonstrate that
the pipeline works end to end on real production code. They are not a catch
rate, because the regression was chosen by the person measuring. Report them as
what they are: an end-to-end proof of mechanism, on two functions, with the
defect known in advance.
