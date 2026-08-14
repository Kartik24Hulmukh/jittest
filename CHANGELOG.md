# Changelog

## 0.3.2 - 2026-08-14

### Documentation & Reproducibility
- 0.3.2 — documentation and reproducibility patch; no behavior change.

## 0.3.1 - 2026-08-13

### Production Hardening & Infrastructure
- **Full Action Security Hardening**: All third-party GitHub Actions across `action.yml` and `.github/workflows/*.yml` are strictly pinned to immutable 40-character commit SHAs. Workflows include `concurrency` cancellation groups and job `timeout-minutes`.
- **Parallel Test File Verification**: `src/jittest/action.py` executes parallel verification across multiple changed test files using `concurrent.futures.ThreadPoolExecutor`.
- **Operations & Security Contracts**: Added `.github/CODEOWNERS`, documented Verdict JSON Schema 2.0 stability contract in [`docs/SCHEMA.md`](file:///C:/Users/praja/src/jittest/docs/SCHEMA.md), and added evidence recomputation instructions in [`docs/evidence/README.md`](file:///C:/Users/praja/src/jittest/docs/evidence/README.md).
- **Usage & Floating Tag Standard**: Standardized usage instructions to `uses: Kartik24Hulmukh/jittest@v0.3.1` (or `@v0`) and configured automatic floating `v0` major tag updates.

## 0.3.0 - 2026-08-12

### Added
- **`jittest/verify-action` GitHub Action (`action.yml`)**: A composite GitHub Action for continuous integration PR verification. Automatically extracts modified test files from PR diffs, executes paired base/head verification, and upserts a single GitHub PR summary comment with verdict tables.
- **Fork PR Sandboxing Policy**: PRs from external forks automatically enforce `sandbox_mode=required` (container/docker namespace isolation) to protect CI runners from untrusted code execution.
- **Four-Quadrant Evidence Artifacts (`docs/evidence/quadrants/`)**: Published 4 signed evidence JSON artifacts covering all verdict states: `proven_catch`, `refuted`, `non_discriminating`, and `inconclusive`.
- **Public Cryptographic Keys Guide (`docs/KEYS.md`)**: Published official project Ed25519 public key (`74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130`), Python verification script, and offline receipt verification documentation.
- **Subprocess Provenance Resolution**: Extended `verify.py` tool provenance to capture `tool_commit_sha`, `tool_branch` (`git rev-parse --abbrev-ref HEAD`), `tool_dirty` (`git status --porcelain`), and `tool_tree_sha` via subprocess execution.

## 0.2.1 - 2026-08-11

### Added & Fixed
- **Loud Environment Provisioning & Preflight Checks**: Removed silent exception suppression during `pip install`. Detailed stdout/stderr tails are logged and raised as `EnvSetupError` (yielding status `ENV_SETUP_FAILED`), preventing environment build failures from masquerading as test verdicts. Virtual environments now undergo strict preflight verification (`python -c "import <pkg>"` and `python -m pytest --version`).
- **Automatic Test Dependency Discovery**: In addition to standard `requirements.txt` and `setup.py`, environment provisioning now parses and installs `requirements-dev.txt`, `requirements/*.txt`, and `pyproject.toml` test/dev extra dependencies (`.[dev,test,tests]`).
- **Receipt Verification Honesty**: In `receipt.py`, Ed25519 signature verification without the `cryptography` package now honestly returns `(False, "UNVERIFIABLE: cryptography package required to verify Ed25519 signature")` instead of claiming valid signature. HMAC-SHA256 signature fallback is strictly documented as integrity-only with zero third-party authenticity guarantees.
- **Benchmark Gate & Fixture Isolation**: Added `--ignore=tests/fixtures` to `tool.pytest.ini_options.addopts` in `pyproject.toml` to keep benchmark gate fixtures isolated from unit test runs. Verified 5/5 hard gate profiles (`bug_flask_01` .. `bug_flask_05`) yielding `proven_catch=true` on Linux/WSL2 environments.
- **v0.2.0 Tag Realignment**: Tag `v0.2.0` realigned to release commit.

### Security
- **Model-written candidate code now executes inside a real confinement boundary.** `src/jittest/sandbox.py` plans isolation per run: podman, then docker, then bubblewrap, with `--network none`, a read-only root filesystem, capabilities dropped, `no-new-privileges`, and pid and memory ceilings; the package root is mounted read-only at `/opt/jittest`. Three modes: `auto`, `required`, `off`; the chosen plan is recorded in the report's `sandbox` block. (#56)
- **`auto` never pulls an image mid-run**, falling back to bubblewrap when the image is absent locally; `required` still accepts the pull. (Defect 73, #56)

### Fixed
- **Isolation failures no longer manufacture verdicts** - `diff_status: "sandbox_unavailable"` with zero findings and zero model requests instead of raising or spending money. (#56)
- **Runs that analysed nothing are named** - `diff_status: "all_targets_ignored"` / `"below_risk_threshold"` replace a report byte-identical to a clean pull request. (#56)
- **The container could not import jittest** - the package root is mounted read-only and container `PYTHONPATH` points there. (Defect 72, #56)
- **A test that purged `sys.modules` without restoring it poisoned later isolation stubs.** (Defect 74, #56)
- **Unpriced models reported a false $0.000 cost.** Every response is now accounted, with `priced: false` and labelled estimates in JSON instead of a bare zero; `JITTEST_MODEL_PRICE='<in>,<out>'` restores the dollar cap. (P-4, #57)
- **The unpriced fallback ceiling now follows resolved config rather than raw environment guesses.** `build_llm()` takes an explicit request ceiling passed by the CLI and both eval harnesses. Covered by `tests/test_request_ceiling.py`. (#62)

### Added
- Action inputs `sandbox` and `model-price`; `.env.example` and `docs/QUICKSTART.md` document sandbox modes, the NVIDIA-compatible endpoint and explicit model pricing. (#62)
- `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `.github/ISSUE_TEMPLATE/` bug and feature forms, and `examples/seeded_regression_demo.py` - a one-command end-to-end demo that builds a seeded regression in a throwaway git repository and runs the full pipeline against it with `--dry-run`; its README states plainly that a stub model yields no candidates, so the oracle does not execute without a key. (#65)
- `tests/test_sandbox.py`, `tests/test_sandbox_image_policy.py`, `tests/test_nothing_analysed.py` (#56), `tests/test_cost_accounting.py` (#57), `tests/test_request_ceiling.py` (#62).
- `JITTEST_SANDBOX` (`auto`/`required`/`off`), `JITTEST_SANDBOX_BACKEND`, `JITTEST_SANDBOX_IMAGE` configuration. (#56)

### Changed (internal, no API change)
- `llm.py` decomposed into `_pricing.py`, `_llmjson.py`, `_llmbase.py`, `_llmcache.py`, `_litellm.py`; `pipeline.py` decomposed into `results.py` and `_pipeline_helpers.py`. Public names re-exported from their original modules. (#57)

### Verified in this release
- 385 offline tests green on two host shapes (with and without a container engine).
- PRs #56, #57, #62 and #65 each landed 18/18 checks. PR #62's lint failure was diagnosed by bisecting CI itself with two throwaway probe pull requests - the violation was I001 (ruff isort order-by-type) on the new regression test's import - and fixed in the source. No rule disabled, no `noqa`, no probe merged.

### Still not fixed
- **No measured catch rate, false-positive rate, or priced cost per pull request exists yet** - the eval workflow is `workflow_dispatch`-only and requires one human click plus a funded key.
- **The false-positive screening harness exists but is not wired into CI** - the prepared `eval.yml` changes cannot be pushed by this automation identity (the platform returns 403 for `.github/workflows/`). Needs one human commit or a permission grant.
- **Container isolation has never run against a real Docker daemon in CI.**
- **The assessor's corrected specification has still never fired on a real bug.**

## 0.2.4 - 2026-07-29

### Security
- **Generated tests no longer inherit the runner's environment.** The child environment is now built from an explicit allowlist, runner credentials are withheld, and an exfiltrator fixture proves the canary does not survive. (#45)
- **Reported failure excerpts are redacted** through `jittest.redact.redact()` after truncation. (#48)

### Fixed
- **A git failure and an empty diff were the same outcome.** `git_diff` now raises `GitError` when every revision spec fails, versus `diff_status: "empty"` for a true empty diff. (#46)
- **The eval harness could not hear `diff_status`.** `classify()` returns a distinct `git_failed` status; the headline `catch_rate` is computed over *eligible* bugs with `catch_rate_all_attempted` beside it.
- **A pytest-style candidate silently became "no tests" on a repository without pytest** - a fixture error is now `EXIT_FAILED`. (#50)
- **`/proc/does-not-exist` is writable on Windows** - `_unwritable_path()` now selects a platform-appropriate path.

### Added
- **A vendored pytest shim** so jittest can run pytest-style tests on repositories without pytest: `fixture`, `mark`, `param`, `approx`, `raises`, `MonkeyPatch`, `importorskip`, function and module scope fixtures, parametrisation, `conftest.py` discovery, and the builtins `tmp_path`, `tmp_path_factory`, `monkeypatch`, `capsys`. (#50)
- `tests/test_minirunner_fixtures.py` and `tests/test_minirunner_fixtures_e2e.py`. (#50)
- `.github/PULL_REQUEST_TEMPLATE.md`. (#51)
- `src/jittest/redact.py` and `tests/test_redaction.py` (18 tests).
- `tests/test_git_failures.py` (14 tests, #46) and `tests/test_eval_git_denominator.py` (14 tests).
- Candidate environment isolation with exfiltrator tests (`tests/test_isolation.py`). (#45)
- Typed candidate dispositions and per-run provenance and completeness records. (#40, #41, #42)

### Verified in this release
- 269 offline tests green before this release's additions, no network required.
- PR #50 landed at 18 of 18 checks; PRs #46 and #48 each landed 18/18 including GitGuardian.
- Four ruff violations on the mini-runner branch were located by bisecting CI itself; every one fixed in the source, no rule disabled, no `noqa`, no probe merged.

### Still not fixed
- **Candidates still share the filesystem, network, and user account with the runner** - the environment allowlist is not a sandbox. (Resolved in Unreleased via #56.)
- No measured catch rate, false-positive rate, or priced cost per pull request exists yet.
- **The assessor's corrected specification has still never fired on a real bug.**

## 0.2.3 - 2026-07-27

### Fixed
- **`git_diff` returned nothing, successfully, whenever head was an ancestor of base** - the three-dot diff is legitimately empty there; the fix falls through to the two-dot spec. This had made every BugsInPy evaluation run see zero changed files while reporting success.
- **The eval harness decided whether a bug had been measured from a stopwatch** - measurement is now defined by whether a model request was issued.
- **`BugResult.seconds` was never assigned on the success path**; `res.caught` was assigned to a non-field attribute; a duplicate local import of `load_config` shadowed the outer one.

### Added
- `Report.model_requests` serialised in `Report.as_dict()`, plus `model_requests` per eval result and `model_requests_total` in the summary.
- `eval/assert_measured.py` and a workflow step that runs it - an evaluation run can no longer report success without measuring anything.
- `tests/test_measurement.py` (12 tests).

## 0.2.2 - 2026-07-27

### Security
- **Safety gate bypasses closed (16 of 22 adversarial payloads accepted before this change).** Added `BANNED_IMPORT_NAMES`, `BANNED_DUNDERS`, builtin-alias detection, constant-string-only `getattr`/`setattr`/`delattr`, and rejection of write-mode `open()` on a constant path.
- **Diff paths can no longer escape the repository** via `diff.is_safe_repo_path`.

### Fixed
- **Config validation** with a per-field range table; rejections and clamps recorded on `cfg.notes`.
- **Git-quoted diff paths** (filenames with spaces) are now unescaped instead of dropped.
- **Version drift** between `pyproject.toml` and `jittest.__version__` pinned by a test.

## 0.2.1 — 2026-07-26

### Fixed
- pytest parity via `pythonpath = ["src"]` in `[tool.pytest.ini_options]`.
- `Outcome` restored to `StrEnum` with 4 regression tests.
- Canonical Apache-2.0 licence; GitHub now detects `spdx_id: Apache-2.0`.
- Ruff compliance: 7 errors fixed, no per-file-ignores, no noqa.

## [0.2.0] - 2026-07-25

### Changed - the zero-dependency rewrite
- **`dependencies = []`.** Own diff parser, `urllib` model access, stdlib `tomllib` config, `argparse` CLI. litellm stays opt-in via `jittest[litellm]`.

### Added
- `_minirunner` stdlib test runner; worktree reuse; flakiness reruns; `jittest doctor`; human outcome labels plus `jittest outcome` and anonymised `jittest export`; static safety gate; response cache; budget cap before a request is sent; `--dry-run`.

## [0.1.0] - 2026-07-25

- First scaffold: diff parsing, risk targeting, generator prompts, differential oracle, assessor, SQLite ledger, GitHub Action, docs and evaluation harness.

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).
