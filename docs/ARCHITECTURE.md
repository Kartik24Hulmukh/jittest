# Architecture

```
  git diff base...head
         |
  [1] diff.py        own unified-diff parser + stdlib ast  ->  ChangeTarget per changed function
         |
  [2] risk.py        explicit heuristic Diff Risk Score  ->  top-K risky symbols only
         |                                              (cost gate: most diffs stop here)
  [3] prompts.py     inverted objective: write a test that FAILS on head
      llm.py         urllib HTTP backend (Anthropic Messages / OpenAI-compatible);
                     litellm is an OPTIONAL extra, not a dependency
         |
  [4] execute.py     THE ORACLE - mechanical, no LLM
         |             run on head  -> must FAIL   (else: hardening test, discard)
         |             rerun x2     -> must FAIL   (else: flaky, discard)
         |             run on base  -> must PASS   (else: pre-existing, backlog)
         |
  [5] assess.py      regression | intended_change | invalid_test
         |             precision stage
         |
  [6] report.py      one PR comment, edited in place, silent when empty
         |
  [7] ledger.py      every candidate + verdict + human outcome -> local SQLite
                       the only part that compounds
```

---

## Module-by-module

### `diff.py` — diff parsing and change-target extraction

Parses unified diffs with a hand-written parser (`parse_unified_diff`). No
external diff library is used. The unit of work is a *symbol* (function or
method), not a file. `extract_targets` maps diff hunks to enclosing symbols
using the stdlib `ast` module's `lineno` / `end_lineno` fields. Also provides
`git_diff` and `git_show` wrappers around the `git` subprocess.

### `risk.py` — risk ranking

An explicit, auditable heuristic (`score_target`) that assigns a risk score to
each `ChangeTarget`. Every reason the heuristic fires is printed in the report
so a maintainer can tell us it is wrong. Deliberately not a learned model; the
roadmap is to replace it once the ledger holds enough labelled outcomes.

### `prompts.py` — prompt construction

Two separated prompts: a *generator* prompt that instructs the model to write a
test that FAILS on the new code, and an *assessor* prompt shown only to tests
that have already survived the mechanical oracle. `existing_tests_block` and
`pr_context_block` format context for the model.

### `llm.py` — model access

Model access over stdlib `urllib`. Supports Anthropic Messages API and any
OpenAI-compatible endpoint directly. `litellm` is supported as an **optional
extra** (`pip install jittest[litellm]` and set `JITTEST_USE_LITELLM=1`); it is
not a runtime dependency. Includes a hard budget cap (`BudgetExceeded`) that
raises before the request is sent, an on-disk response cache (`_Cache`), and a
`DryRunLLM` backend for zero-cost pipeline testing.

### `execute.py` — the differential oracle

The load-bearing module. Keeps a candidate test if and only if it FAILS on
head, the failure reproduces across reruns, and it PASSES on base. No model is
consulted. Uses `detect_runner` to find pytest or fall back to `_minirunner`.
`Worktree` manages git worktrees for base and head commits. `differential_check`
orchestrates the full oracle sequence.

### `_minirunner.py` — stdlib test runner fallback

A minimal test runner used only when pytest is not importable. Loads test
modules via `importlib`, collects `test_*` functions, and runs them with
`asyncio` support for async tests. Exit codes mirror pytest (0 = pass, 1 =
fail, 2 = collection error, 5 = no tests) so the oracle needs no special
cases. Exists so jittest can answer "does this test pass here?" in
environments where nothing can be installed.

### `assess.py` — assessor layer

Parses the assessor model's JSON response into an `Assessment` with a
classification (`regression`, `intended_change`, or `invalid_test`) and a
confidence score. Only a confident `real_regression` is reported by default.

### `safety.py` — static gate on generated code

An AST-based check (`check_candidate`) applied to model-written test code
before execution. Bans network calls, subprocess invocation, file writes, and
other operations that have no business running in someone else's CI. This is a
static check, not a security boundary.

### `config.py` — configuration

Precedence chain: dataclass defaults → `.jittest.toml` → `[tool.jittest]` in
`pyproject.toml` → `JITTEST_*` environment variables → command-line flags.
Read with stdlib `tomllib`. No PyYAML, no pydantic.

### `cli.py` — command-line interface

Built with stdlib `argparse`. Subcommands: `run` (full pipeline), `doctor`
(environment check), `stats` (ledger summary), `export` (corpus export),
`outcome` (record human decision). No Typer, Click, or Rich.

### `github.py` — GitHub client

Minimal GitHub API client over stdlib `urllib`. One job: upsert a single PR
comment so the bot never spams a thread. Falls back to `gh` CLI if no token is
present. No PyGithub dependency.

### `ledger.py` — the ledger

Records every candidate, every oracle verdict, and every human reaction to a
local SQLite database. Nothing leaves the machine. The `Candidate` and
`Ledger` classes manage insertion, querying, and export. This is the
long-term asset: a labelled corpus of real diffs, generated candidates,
mechanical outcomes, and human decisions.

### `pipeline.py` — orchestration

Coordinates the full pipeline: diff → change targets → risk ranking →
candidate generation → safety gate → differential oracle → assessor → ledger +
report. `run` is the main entry point. Base and head worktrees are created
once per run and reused for every candidate.

### `report.py` — report rendering

Two rules: (1) if nothing is proven, say nothing — jittest posts no comment
when it finds no catching test; (2) every claim is reproducible in one
command, printed next to the claim. `to_markdown` produces the PR comment;
`to_terminal` produces CLI output.

---

## The four design commitments

### 1. The oracle is mechanical, not model-judged
A model never decides whether a test is a catching test. Execution does. This
is what separates jittest from every "AI finds bugs in your PR" tool: our
findings are reproducible by the reviewer in one command. When a model is
wrong we waste tokens; we do not waste the reviewer's trust.

### 2. Silence is the default output
Most PRs should produce no comment. The failure mode that kills this category
is noise. Every threshold in the codebase (`risk_threshold`,
`MIN_CONFIDENCE`, `max_targets`) is tuned toward silence. Move them up on
evidence, never down for demo purposes.

### 3. The assessor is the product; the generator is a commodity
An LLM-plus-test-runner is six weeks of work for any competent team. What is
not copyable is a labelled corpus of `(diff, candidate test, mechanical
outcome, human decision)`. `ledger.py` exists from commit one for this reason,
even though at v0.2 it does nothing but record.

### 4. Cost is a first-class constraint
Hard budget cap per run, enforced mid-loop, not after. A tool that surprises
someone with a bill gets uninstalled and posted about.

---

## Extension points (in the order they should be built)

| Point | Interface | Version |
|---|---|---|
| Sandbox backend | `execute.Worktree` → `SandboxBackend` protocol | v0.4 |
| Language | `diff._enclosing_symbols` → tree-sitter grammar per language | v0.6 (Java first, for Defects4J) |
| Risk model | `risk.score_target` → learned model from ledger | v0.4 |
| Test runner | pytest subprocess → runner plugin (unittest, JUnit) | v0.6 |
| Forge | GitHub `gh` CLI → GitLab / Bitbucket adapters | v0.5 |

---

## What we deliberately do not build

- A web dashboard. The PR comment is the interface.
- A hosted service before 20 teams use the CLI.
- Autofix. Proposing the fix reintroduces the trust problem the oracle solves.
- A VS Code extension. Wrong surface: catching tests are a review-time artifact.
- Multi-language support at launch. One language done properly beats four done
  badly, and Python is where the AIDev agentic-PR evidence is.
