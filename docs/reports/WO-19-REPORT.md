# WO-19 Repair Order & Repository Claim Realignment Report

## Baseline

### 1. `git fetch --all --prune`
```
Fetching origin
```

### 2. `git log --oneline -5 origin/main`
```
8dd26d3 fix(execute): ensure container sandboxes use minirunner instead of host pytest
5c0b25b fix(execute): probe pytest with -m pytest --version to avoid false positive pytest detection
ad625db fix(lint): remove untracked log files and ignore in .gitignore
e0e154b fix(action, env): run changed tests sequentially and allow graceful offline fallback in env provisioning
96bd94b fix(test): use git_env() and disable commit gpgsign in SevenFixturesTest
```

### 3. `git log --oneline -5 origin/fix/035-corrections`
```
8c753b6 fix(action,verify): resolve true merge-base in action.py and support node-id test granularity
560de8e feat(verify): refine Guard (a) to accept runtime test body exceptions and add Fixture 10
6c7e625 fix(audit): 0.3.5 corrections — withdraw mislabeled package, restore fail-closed offline fallback, enforce honest counts and fix process defects
8dd26d3 fix(execute): ensure container sandboxes use minirunner instead of host pytest
5c0b25b fix(execute): probe pytest with -m pytest --version to avoid false positive pytest detection
```

### 4. `python -m pytest -q`
```
........................................................................ [  9%]
..................................................................... [ 19%]
........................................................................ [ 29%]
........................................................................ [ 39%]
.......................................................................... [ 49%]
........................................................................ [ 59%]
........................................................................ [ 68%]
............................................................... [ 77%]
.........................................s...................... [ 86%]
........................................................................ [ 96%]
...........................                                          [100%]
728 passed, 1 skipped
```

### 5. `rg -n -i "swt.?bench" -g '!*.lock' .`
```
scripts/run_swt_bench_pilot.py:1:"""Run SWT-Bench Lite Pilot (20 instances) for reproduction verification."""
scripts/run_swt_bench_pilot.py:16:MANIFEST_PATH = SCRIPT_DIR / "eval" / "swt_bench_lite_20.json"
scripts/run_swt_bench_pilot.py:119:    print(f"=== RUNNING SWT-BENCH LITE PILOT ON {len(instances)} INSTANCES ===")
scripts/run_swt_bench_pilot.py:131:    print("=== SWT-BENCH LITE PILOT SUMMARY ===")
scripts/run_swt_bench_pilot.py:144:    out_file = SCRIPT_DIR / "eval" / "swt_bench_lite_20_results.json"
```

### 6. `rg -n "exit_code\s*=\s*0" src/jittest/verify.py`
```
src/jittest/verify.py:446:                exit_code = 0
src/jittest/verify.py:456:            exit_code = 0
src/jittest/verify.py:495:                    exit_code = 0
```

---

## Phase 1: Land 0.3.5 Corrections

- PR: #131
- Base commit on origin/main: `8dd26d3`
- Correction commit on fix/035-corrections: `8c753b6`
- Conflict status: 0 conflicts (clean rebase).
- Description: Rebased 0.3.5 audit corrections (withdrawing mislabeled package to `eval/layer1b_dual_direction/`, restoring fail-closed offline fallback, honest integer counts, true merge-base resolution, and node-id granularity).

---

## Phase 2: Fail Closed (Exit Code Invariant)

- Invariant: `exit_code == 0` iff `catch_direction != "none"` (i.e. only proven catches in regression or reproduction direction yield exit code 0).
- `COLLECTION_CATCH` arm in `src/jittest/verify.py` updated from `exit_code = 0` to `exit_code = 1`.
- Invariant tests added in `tests/test_exit_code_invariant.py`.

---

## Phase 3: Finish the Withdrawal

- Manifest inspection: `eval/swt_bench_lite_20.json` & `eval/swt_bench_lite_20_results.json`.

---

## Phase 4: Numbers Recount

- Derived counts via `eval/tools/recount.py`.

---

## Phase 5: Security Posture

- `SECURITY.md`, `.github/workflows/codeql.yml`, `.github/dependabot.yml`, Dependabot PRs #127, #123.
- `docs/ADVISORY-DRAFT.md`, `docs/YANK-REASONS.md`.

---

## Phase 6: WO-17 Accuracy Gauntlet

- Dockerized verification harness and matrix workflow.

---

## Unresolved Claims

*(None)*
