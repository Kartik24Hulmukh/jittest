# The Null Results of Generator-Track Test Synthesis

## Abstract & Executive Summary

Between August 2026 and August 2026, the `jittest` project designed, implemented, and preregistered two generations of automated "catching test" generators:
1. **Phase C (Direct Synthesis)**: Prompting LLMs to write catching tests directly from PR diff context.
2. **Phase D (Differential Explorer)**: Mutation-first seed generation, mechanical AST repairs, paired base/head execution, changed-line feedback, and oracle-last synthesis (`C-PHASE-D-FIX-2`).

Both instruments were evaluated against the 7 real Flask calibration rows under strict, preregistered protocols with metered execution and zero holdout tuning.

**Primary Result**: Both instrument tracks yielded **0/7 catches (0.0%)**.

Rather than continuing to tune prompts or repair edge-case collection failures in an endless cycle of benchmark overfitting, the `jittest` project closed the generator track permanently and pivoted to the **Evidence Layer (`jittest verify`)**.

---

## Provenance Receipts & Benchmark Costs

| Instrument Track | Preregistration SHA | Manifest SHA256 | Real Executed Candidates | Catches | Total Provider Spend |
| :--- | :--- | :--- | :---: | :---: | :---: |
| **Phase C (Direct)** | [`090d071fd0127428b17eb3c2f50c66312461a856`](https://github.com/Kartik24Hulmukh/jittest/commit/090d071fd0127428b17eb3c2f50c66312461a856) | `e6632b71a023e7004b27837375c61b820822156cac2ed4cfb020388bbcefa630` | 0 / 7 | **0 / 7 (0.0%)** | $0.00 USD (Read-Only) |
| **Phase D (Differential)** | [`0c833f954737868c69198d7bcaff7ec69f74f4c7`](https://github.com/Kartik24Hulmukh/jittest/commit/0c833f954737868c69198d7bcaff7ec69f74f4c7) | `e6632b71a023e7004b27837375c61b820822156cac2ed4cfb020388bbcefa630` | 6 / 7 | **0 / 7 (0.0%)** | $0.0199215 USD |

**Total Cumulative Provider Cost Across Both Null Studies**: **~$0.05 USD**.

---

## Why the Generator Track Failed

1. **Paired Execution Symmetry**: Generating a test that executes cleanly on Python repositories requires deep runtime state (mock objects, test fixtures, import context). When an LLM generates a candidate test, it either:
   - Fails with an exception/syntax error on both commits (e.g. `collection_import_failed`).
   - Asserts a generic property that passes on both commits (hardening test, `head_passed`).
   - Asserts an invalid property that fails on both commits (`latent`).
2. **Zero Paired Differences**: Across 6 candidates that executed on real worktrees under Phase D (`bug_flask_01` through `bug_flask_07`), **zero candidates exhibited a paired behavioral difference** (passing on base while failing on head).

---

## The Pivot to Evidence-Layer Verification (`jittest verify`)

The fundamental insight gained from the null studies is:

> **Generating tests is cheap and plentiful (coding agents write them continuously). Proving that a test actually catches a regression across paired base/head commits with zero trust is hard.**

`jittest` now shifts focus entirely from generating tests to **verifying** them:
- `jittest verify --repo <path> --base <base_sha> --head <head_sha> --test <file>`
- Paired base/head execution in isolated git worktrees.
- Signed JSON evidence artifact with exit codes, stdout/stderr hashes, and git rev-parse provenance.
- CI-usable exit codes (`0` for `proven_catch`, `1` otherwise).
