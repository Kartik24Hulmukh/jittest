<h1 align="center">jittest</h1>

<p align="center">
  <b>Generate tests that FAIL on your pull request and PASS on main.</b><br>
  The open reference implementation of just-in-time <i>catching</i> test generation.
</p>

<p align="center">
  <img alt="license" src="https://img.shields.io/badge/license-Apache--2.0-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="dependencies" src="https://img.shields.io/badge/dependencies-0-brightgreen">
</p>

---

## The distinction the whole tool rests on

Almost every AI testing tool generates tests that **pass** on your new code.
That is a *hardening* test. It documents what the code does today, including any
bug you just introduced. Generate tests until they go green and you can
[reinforce the bug you were trying to find](https://arxiv.org/pdf/2412.14137).

jittest generates **catching** tests:

> A catching test **passes on the base commit** and **fails on the head commit**,
> proving the change broke something.

That is not a prompt instruction we hope the model follows. It is a mechanical
gate. Every candidate is executed on both commits, and anything that does not
satisfy the rule is thrown away before you ever see it.

Meta published this method in 2026 and reported catching tests being produced at
roughly **4x the rate of hardening tests**, with assessor agents cutting reviewer
load by about **70%** ([arXiv 2601.22832](https://arxiv.org/abs/2601.22832)).
There was no open implementation. This is one.

## Install

```bash
pip install jittest
```

**Zero dependencies.** Not "few" — zero. jittest runs inside your CI, and a CI
tool has no business injecting a dependency tree into your locked project. Diff
parsing, HTTP, config and the test-runner fallback are all standard library.

## Try it in 60 seconds, with no API key

```bash
cd your-repo
jittest doctor                      # can this environment run jittest?
jittest run --base main --head HEAD --dry-run
```

`--dry-run` runs the real diff parser, the real risk ranker, the real git
worktrees and the real oracle, with a stub model. No key, no network, no cost.
Watch what it targets before you decide whether to hand it a key.

Then, for real:

```bash
export JITTEST_API_KEY=sk-...
jittest run --base main --head HEAD --budget 1.00
```

## In GitHub Actions

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
        with:
          fetch-depth: 0            # the oracle needs both commits
      - uses: Kartik24Hulmukh/jittest@v0
        with:
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
          budget: "1.00"
          comment: "true"
        env:
          JITTEST_API_KEY: ${{ secrets.JITTEST_API_KEY }}
```

**If jittest proves nothing, it posts nothing.** No "looks good to me", no
summary of your diff, no comment at all. Silence is the default and it is a
feature: 2026 surveys put 15–30% of AI review comments in the low-value bucket,
and the cost of that is not tokens, it is the maintainer who turns the bot off.

## What a finding looks like

> #### 1. `billing/calc.py::apply_discount`
> **Removing the clamp lets a discount above 100% return a negative price.**
> > Should a discount over 100% still floor the price at zero?
>
> <sub>assessor: likely regression (confidence 0.88, severity high) — risk score
> 0.71 [consequential_domain, branch_density, modifies_existing]</sub>
>
> ```python
> from billing.calc import apply_discount
>
> def test_discount_never_goes_below_zero():
>     assert apply_discount(100.0, 150.0) == 0.0
> ```
>
> <details><summary>Reproduce locally</summary>
>
> ```bash
> git checkout a1b2c3d4e5f6 && pytest billing/calc.py -q   # expect FAIL
> git checkout 0f9e8d7c6b5a && pytest billing/calc.py -q   # expect PASS
> ```
> </details>

Every claim ships with the command that reproduces it. You should never have to
take our word for anything.

## How it works

```
git diff
  → change targets          functions, not files
  → risk ranking            the cost gate: only the top N symbols are worth tokens
  → N candidate tests       the only step a model decides anything
  → static safety gate      no sockets, no subprocesses, no eval, no assert True
  → DIFFERENTIAL ORACLE     fails on head ∧ reproduces ∧ passes on base
  → assessor                proven true — but would a human care?
  → ledger + report
```

The oracle is the product. Everything else is replaceable.

| Oracle result | What it means | What jittest does |
| --- | --- | --- |
| fails on head, passes on base | the change broke behaviour | **report it** |
| passes on head | hardening test | discard |
| fails on both | pre-existing fault | `--latent` only |
| does not reproduce | flaky | discard |
| cannot be collected | broken test | discard, retry once |

## Commands

```bash
jittest run       --base main --head HEAD [--dry-run] [--comment] [--latent]
jittest doctor    # environment check
jittest stats     # what the local ledger has learned
jittest outcome <test-hash> fixed_code|kept_test|intended|false_positive|ignored
jittest export    corpus.jsonl        # anonymised by default
```

`jittest outcome` is the important one. It records what a human actually did
after seeing a finding, which is the only honest measure of precision — and,
accumulated across repositories, the training signal for a risk model that no
amount of prompt engineering can substitute for.

## Configuration

Precedence: defaults → `.jittest.toml` or `[tool.jittest]` in `pyproject.toml`
→ `JITTEST_*` environment variables → CLI flags.

```toml
[tool.jittest]
model = "z-ai/glm-5.2"      # configured via repository variables; any OpenAI-compatible provider works
budget_usd = 1.00          # hard cap for priced models; unpriced models use a request-count ceiling
max_targets = 5
candidates_per_target = 4
risk_threshold = 0.35
reruns = 2                 # flakiness reruns on head
ignore = ["legacy/*"]      # added to the built-in defaults
```

Any OpenAI-compatible endpoint works via `JITTEST_API_BASE`, including local
Ollama. For the long tail of providers, `pip install jittest[litellm]` and set
`JITTEST_USE_LITELLM=1`.

## Honest status

This is **v0.2.1, alpha**. What is verified and what is not:

| | Status |
| --- | --- |
| Oracle, pipeline, safety gate, ledger, config, CLI, telemetry | 144 offline tests, green, no network required |
| Oracle behaviour on a real seeded regression in a real git repo | tested |
| Catch rate on a public benchmark (BugsInPy) | **not yet measured** — harness in `eval/` |
| False-positive rate on real PRs | **not yet measured** |
| Cost per PR in practice | target under $1.00; **not yet measured at scale** |

We will publish those numbers when we have run them, with the methodology and
the failures included. Until then they are blank rather than optimistic. If you
see a benchmark claim in this README that is not backed by a script in `eval/`,
it is a bug — please file it.

## Privacy & Candidate Source Retention

By default, generated candidate source files are persisted locally under `~/.jittest/candidates/<run_id>/` for local auditability. Candidate source code is **never** included in telemetry outputs or public logs.

To disable writing candidate files to disk, set `JITTEST_PERSIST_CANDIDATES=0` or pass `--no-persist-candidates`.

## Docs

- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) — five minutes, no key
- [`docs/DIFFERENTIATION.md`](docs/DIFFERENTIATION.md) — why another one of these
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the pipeline in detail
- [`docs/PAPERS.md`](docs/PAPERS.md) — the research this implements
- [`docs/PRIOR-ART.md`](docs/PRIOR-ART.md) — what exists and how this differs
- [`SECURITY.md`](SECURITY.md) — we execute model-written code; read this

## Citing

If jittest helps your research, cite the method
([arXiv 2601.22832](https://arxiv.org/abs/2601.22832)) and this implementation
(see `CITATION.cff`).

## Licence

Apache-2.0.
