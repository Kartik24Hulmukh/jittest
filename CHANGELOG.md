# Changelog

## 0.2.2 - 2026-07-27

### Security
- **Safety gate bypasses closed (16 of 22 adversarial payloads were accepted before this change).** An adversarial sweep of `safety.check_candidate` found six independent classes of bypass: `from os import system` style imports (the module was allowed and the callee arrived as a bare `Name`), builtin aliasing (`f = eval` then `f(...)`), reflection (`getattr`, `importlib.import_module`, `builtins.eval`, `runpy.run_module`), interpreter gadgets (`''.__class__.__mro__[1].__subclasses__()`, `func.__globals__`), filesystem mutation, and vacuous asserts (`assert 1`). The filesystem class was the most serious: a candidate test that rewrites a worktree source file can manufacture a base/head difference and therefore forge an oracle catch, which would corrupt the one signal in this project that has been trustworthy. Added `BANNED_IMPORT_NAMES`, `BANNED_DUNDERS`, alias detection for banned builtins referenced without being called, constant-string-only `getattr`/`setattr`/`delattr`, and rejection of write-mode `open()` on a constant path. `__class__`, `str.replace`, `list.remove` and `file.write` remain allowed because they are ubiquitous in legitimate tests. Post-fix sweep: 0 dangerous payloads accepted, 0 legitimate payloads rejected, 4000-input fuzz with no crashes.
- **Diff paths can no longer escape the repository.** The parser yielded `../../etc/passwd` and `/etc/shadow` as change targets, and those paths flow into `git show <rev>:<path>` and worktree writes. Added `diff.is_safe_repo_path` (rejects empty paths, null bytes, absolute paths, UNC paths, drive letters, any `..` segment, control characters) and enforced it in `extract_targets`.

### Fixed
- **Config validation.** `load_config` accepted wrong types and out-of-range values: `budget_usd = "lots"` stayed a string, `risk_threshold = 5.0` was accepted (producing a run that analyses nothing while reporting success), and `JITTEST_BUDGET_USD=nan|inf|1e400` produced a config whose `as_dict()` was not strict-JSON serialisable, silently corrupting the telemetry artifact the eval harness reads. Added `normalise_values()` with a per-field range table; unknown keys are dropped, bools are rejected where numbers are expected, non-finite values are rejected, and out-of-range values are clamped. Rejections and clamps are recorded on `cfg.notes`, a non-field attribute, so `as_dict()` stays strictly serialisable.
- **Git-quoted diff paths were silently dropped.** Any change to a file whose name contains a space was invisible to jittest. The `diff --git` header matcher now handles quoted paths and unescapes them.
- **Version drift.** `pyproject.toml` and `jittest.__version__` were maintained independently and had already diverged. Added a test that fails when they disagree.

### Added
- `tests/test_hardening.py` - 21 tests covering safety-gate bypasses (17 must-reject and 10 must-accept payloads plus a 500-input fuzz), config normalisation including a strict-JSON environment sweep, diff path safety including a 400-input mutation fuzz, and assessor confidence coercion.

### Not fixed in this release
- The assessor still labels every oracle-confirmed catch `intended_change` at high confidence, so nothing is ever reported to a pull request. This is the launch-blocking defect and it cannot be settled with self-mutation canaries; it needs real bugs.

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
