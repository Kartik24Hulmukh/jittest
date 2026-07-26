# Technology stack

The rule: **write only the differential oracle, the risk targeter, the
assessor, and the ledger.** Everything else is stdlib or an optional extra.
If you find yourself building infrastructure, stop and check whether the
standard library already has it.

---

## Runtime dependencies

**None.** `pyproject.toml` declares `dependencies = []`.

jittest runs inside other people's CI, and every dependency we add is a
resolver conflict in somebody's locked project. Diff parsing, HTTP, config,
test running, and the test-runner fallback are all stdlib.

---

## What we use from the standard library

| Need | Module | How |
|---|---|---|
| Parse unified diffs | — (own parser) | `diff.py` contains a hand-written unified-diff parser. No `unidiff` dependency. |
| Map lines to functions | `ast` | `ast.lineno` and `ast.end_lineno` give symbol boundaries. Tree-sitter only when we add non-Python languages. |
| HTTP to LLM providers | `urllib.request` | `llm.py` posts to Anthropic Messages and OpenAI-compatible endpoints directly. |
| GitHub API | `urllib.request` | `github.py` upserts PR comments via the REST API. No PyGithub. |
| Config | `tomllib` | `config.py` reads `.jittest.toml` and `[tool.jittest]` from `pyproject.toml`. No PyYAML. |
| CLI | `argparse` | `cli.py` has subcommands: `run`, `doctor`, `stats`, `export`, `outcome`. No Typer, Click, or Rich. |
| Test runner fallback | `importlib`, `asyncio`, `inspect` | `_minirunner.py` loads and runs `test_*` functions when pytest is absent. |
| Corpus storage | `sqlite3` | `ledger.py` stores candidates, verdicts, and human outcomes locally. Inspectable, diffable, zero infra. |
| Isolation | `subprocess` + git worktree | `execute.py` runs tests in a temp worktree with a hard timeout. |

---

## Optional extras

| Extra | Install | What it provides |
|---|---|---|
| `litellm` | `pip install jittest[litellm]` | Access to 100+ LLM providers through a single interface. Used instead of the built-in urllib HTTP backend when `JITTEST_USE_LITELLM=1` is set. Not required for the core pipeline. |
| `dev` | `pip install jittest[dev]` | pytest, pytest-timeout, ruff, mypy — for contributors. |

---

## Isolation: why git worktree is enough for v0.2

We execute LLM-generated code. That is genuinely dangerous — but in CI the
runner is an ephemeral container that is destroyed after the job, and the code
under test is the user's own repository.

v0.2 mitigations: `safety.py` static AST gate before execution, hard subprocess
timeout, `PYTHONDONTWRITEBYTECODE`, temp worktrees removed on exit.

**When someone wants to run jittest locally or on a self-hosted runner, this is
not enough.** Pluggable backend lands in v0.4. The `Worktree` interface in
`execute.py` is the extension point.

---

## Evaluation stack

| Need | Source |
|---|---|
| Real Python bugs | BugsInPy (`soarsmu/BugsInPy`) |
| Real Java bugs | Defects4J (`rjust/defects4j`) |
| Low-memorisation bugs | GitBug-Java (`gitbugactions/gitbug-java`) |
| Synthetic regressions | Cosmic Ray (`sixty-north/cosmic-ray`) or mutmut (`boxed/mutmut`) |

The BugsInPy inversion trick: each entry has a buggy commit and a fixed
commit. Treat `fixed → buggy` as a synthetic regression PR. A perfect jittest
run produces a test that passes on `fixed` and fails on `buggy`.

Watch for data leakage: BugsInPy and Defects4J are in The Stack and models
memorise them. Report GitBug-Java numbers alongside, and hold out a private
set of recent real regressions.

---

## Packaging and distribution

| Need | Choice | Why |
|---|---|---|
| Build backend | Hatchling | Sane defaults, trivial GitHub Actions release. |
| Lint/format | Ruff | One tool, fast. |
| CI | GitHub Actions | Where the users are. |
| Distribution surface | Composite GitHub Action | Not Docker: composite actions start faster and let the target repo's own environment install itself. |
| Registry | PyPI + GitHub Marketplace | Two search surfaces for one artifact. |

---

## What is deliberately NOT a dependency

LangChain, LlamaIndex, any agent framework, any vector database, Docker at
runtime, Postgres, Redis, a web app, unidiff, litellm (at runtime), pydantic,
typer, rich, PyYAML, coverage. Every one of these is a week you do not have,
and most are a resolver conflict in somebody's locked project.
