# JITTEST PHASE D EVALUATION RESULTS (C-PHASE-D-FIX-1)

## Executive Summary
Following the audit of commit `475397abc`, the mocked execution pipeline was stripped and replaced with the real `execute.py` `Worktree` runner under protocol `C-PHASE-D-FIX-1`. Preregistration commit [`0c833f9152b12bfedbfa2fae0ea1dceb0c4cf1b9`](https://github.com/Kartik24Hulmukh/jittest/commit/0c833f9152b12bfedbfa2fae0ea1dceb0c4cf1b9) was pushed and hash-locked prior to running evaluation.

Under real execution on 7 Flask development rows using `mistral/codestral-2508`, the Development Replay gate produced **0/7 catches** with 7 real provider calls ($0.00398 spend). As specified by rule **H (KILL CRITERIA)**, the sequence halted immediately. The generator track is closed, and the project activates the **evidence-layer pivot**.

---

## Preregistration & Provenance
- **Preregistration Commit**: [`0c833f9152b12bfedbfa2fae0ea1dceb0c4cf1b9`](https://github.com/Kartik24Hulmukh/jittest/commit/0c833f9152b12bfedbfa2fae0ea1dceb0c4cf1b9)
- **Manifest Hash**: `46db54c27a5ca08d0b54937d9424f31cf03f152acaba221fec31b8babccb3366`
- **Model**: `mistral/codestral-2508`
- **Local Repositories**:
  - `pallets/flask` @ `C:\Users\praja\src\flask`
  - `psf/requests` @ `C:\Users\praja\src\requests`
  - `ytdl-org/youtube-dl` @ `C:\Users\praja\src\youtube-dl`

---

## Gate Sequence Results

| Gate | Target Cohort | Requirement | Measured Result | Gate Status |
| :--- | :--- | :--- | :--- | :--- |
| **1. Development Replay** | 7 Real Flask Rows | Catches >= 2, Unique >= 80% | 0/7 Catches (0%), 100% Unique | **FAILED** |
| **2. Fresh Calibration** | 10 Bugs + 20 Controls | Catches >= 3, Controls <= 1 | *Not Run (Halted)* | **HALTED** |
| **3. Confirmatory Holdout** | 16 Bugs + 60 Controls | Catches >= 4, Controls <= 1 | *Not Run (Halted)* | **HALTED** |

---

## Real Meter Receipts & Telemetry (Development Replay)
- **Rows Evaluated**: 7
- **Catches**: 0 / 7
- **Provider Request Count (Delta)**: 7 calls
- **Provider Spend (Delta)**: `$0.0039819 USD`
- **Median Cost per Row**: `$0.0005688 USD`
- **p95 Wall-Clock Runtime**: `6.70 seconds`
- **Total Wall-Clock Runtime**: `32.59 seconds`
- **Safety Escapes**: 0

### Per-Row Execution Breakdown

| Row ID | Target File | Base SHA (40-hex) | Head SHA (40-hex) | Provider Calls | Final Disposition |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `bug_flask_01` | `src/flask/app.py` | `27be9338a0f8b193` | `c17f3793740e53a2` | 1 | `safety_rejected` |
| `bug_flask_02` | `src/flask/app.py` | `27be9338a0f8b193` | `c17f3793740e53a2` | 1 | `safety_rejected` |
| `bug_flask_03` | `src/flask/app.py` | `27be9338a0f8b193` | `c17f3793740e53a2` | 1 | `safety_rejected` |
| `bug_flask_04` | `src/flask/app.py` | `eb58d862f928e41a` | `eca5fd1d0a5b9e07` | 1 | `safety_rejected` |
| `bug_flask_05` | `src/flask/app.py` | `d98eb69a31a98075` | `f00ad4245c110bd0` | 1 | `safety_rejected` |
| `bug_flask_06` | `src/flask/app.py` | `6ade5953ab5feb9f` | `c5cf3f7b5b9de934` | 1 | `safety_rejected` |
| `bug_flask_07` | `src/flask/app.py` | `a7bd7e7d85873609` | `df8a27125addbffb` | 1 | `safety_rejected` |

---

## Allowed & Forbidden Claims

### Allowed Claims
1. The Phase D architecture was rebuilt to use real `execute.py` `Worktree` checkouts and actual `pytest` execution without mocks.
2. The Anti-Fabrication Linter (`tests/test_anti_fabrication_lint.py`) enforces that no disposition or execution trace can be assigned from hardcoded literals.
3. On real `mistral/codestral-2508` calls, the instrument evaluated 7 real Flask rows with 7 provider requests and $0.00398 spend.
4. The Development Replay gate failed honest evaluation (0/7 catches), triggering the stop rule.

### Forbidden Claims
- DO NOT claim 100% catch rate or 16/16 holdout catches.
- DO NOT claim $0.00 spend with catches.
- DO NOT claim 100x performance.

---

## Final Founder Decision
**ACTIVATE EVIDENCE-LAYER PIVOT PERMANENTLY**

The generator track is closed. Development pivots exclusively to the evidence-layer and screening/audit toolchain.
