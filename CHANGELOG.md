# Changelog

## 0.2.1 — 2026-07-26

### Fixed
- **pytest parity**: Added `pythonpath = ["src"]` to `[tool.pytest.ini_options]` so `python -m pytest` can import jittest from src-layout without `PYTHONPATH`. The unittest runner worked because CI set `PYTHONPATH=src` explicitly; pytest had no such configuration.
- **Outcome enum restored to StrEnum**: Ruff rule UP042 was applied as `Outcome(str, Enum)` → `Outcome(Enum)`, which removed string behaviour the codebase relies on (`Outcome.PASS == "pass"`, JSON serialisation). Corrected to `Outcome(StrEnum)`. Added 4 regression tests that fail on plain Enum and pass on StrEnum.
- **Canonical Apache-2.0 licence**: Replaced placeholder LICENSE with verbatim text from apache.org. GitHub now detects `spdx_id: Apache-2.0` instead of `NOASSERTION`.
- **Ruff compliance**: Fixed all 7 ruff errors (UP042, UP037 ×2, F401, UP012, SIM102, SIM117). No per-file-ignores, no noqa comments, no config relaxation.

### Changed
- **ARCHITECTURE.md and STACK.md rewritten**: Both documents described a v0.1 design that depended on unidiff, litellm, pydantic, typer, rich, PyYAML and coverage. The shipped v0.2 code depends on nothing. Documents now describe what each module in `src/jittest/` actually does, module by module.
- **install-smoke workflow**: Added `.github/workflows/install-smoke.yml` that verifies `pip install .` produces a working `jittest` command on Python 3.11, 3.12 and 3.13. All three pass.
- **CI umbrella job**: Added a `ci` job to `.github/workflows/ci.yml` that aggregates lint, test and build results into a single check name matching the branch protection required context.
- **Actions version bumps**: actions/checkout v4→v7, actions/setup-python v5→v7, actions/upload-artifact v4→v7, softprops/action-gh-release v2→v3.

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-25

### Changed - the zero-dependency rewrite

- **`dependencies = []`.** jittest now installs with no third-party packages at
  all. `unidiff`, `litellm`, `pydantic`, `typer`, `rich` and `PyYAML` are gone.
  A tool that runs inside other people's CI should not bring a dependency tree
  into their locked project, and every package we drop is one fewer resolver
  conflict, one fewer supply-chain surface and one fewer reason to say no.
  - unified diff parsing: own parser in `diff.py`
  - model access: `urllib` in `llm.py` (Anthropic Messages + OpenAI-compatible)
  - config: stdlib `tomllib`
  - CLI: `argparse`
  - litellm is still supported, opt-in, via `pip install jittest[litellm]` and
    `JITTEST_USE_LITELLM=1`

### Added

- **`_minirunner`**: a stdlib test runner used when pytest is not importable,
  with pytest-compatible exit codes (0 pass / 1 fail / 2 collection error /
  5 no tests). jittest can now answer "does this test pass here?" in hardened
  or air-gapped runners.
- **Worktree reuse.** Base and head are checked out once per run instead of once
  per candidate. This is what makes three executions per candidate affordable,
  and three executions is what buys the flakiness rerun.
- **Flakiness reruns** (`--reruns`, default 2). A failure on head must reproduce
  before we spend a base checkout, let alone a reviewer's attention.
- **`jittest doctor`**: reports python version, git, runner, key presence and
  effective config, so a failed install is diagnosable in one command.
- **Human outcome labels** in the ledger (`fixed_code`, `kept_test`, `intended`,
  `false_positive`, `ignored`) plus `jittest outcome` and anonymised
  `jittest export`. This is the corpus, and it is the only asset here that
  cannot be reimplemented in a fortnight.
- **Static safety gate** (`safety.py`) applied to every candidate before it is
  executed: no sockets, no subprocesses, no `eval`, no `assert True`, no sleeps.
- **Response cache** keyed on model, prompts and temperature, so re-running a PR
  costs nothing.
- **Budget cap** enforced before a request is sent rather than after.
- **`--dry-run`** runs the entire pipeline with a stub model: no API key, no
  network, no cost. It is how the test suite runs, and how a new user can watch
  jittest work on their own repo before handing over a key.
- 36 offline tests covering the diff parser, risk ranking, config precedence,
  the safety gate, assessment parsing, the ledger, the oracle against a real
  seeded regression in a real git repo, and the pipeline end to end.

### Fixed

- Candidate test files are always deleted from the checkout, including after a
  timeout.
- `PYTHONHASHSEED=0` and `PYTHONDONTWRITEBYTECODE=1` in the child environment,
  removing one avoidable source of non-determinism.
- Assessor replies with a confidence of `85` are read as `0.85`; unparseable
  replies degrade to `unclear`, which is not reported. The layer fails closed.

## [0.1.0] - 2026-07-25

- First scaffold: diff parsing, risk targeting, generator prompts, differential
  oracle, assessor, SQLite ledger, GitHub Action, docs and evaluation harness.
