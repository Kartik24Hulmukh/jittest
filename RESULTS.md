# Phase D Evaluation Results & Release Decision Report

## Executive Summary & Founder Decision
- **Instrument**: Phase D Differential Explorer (`feat/phase-d-differential-explorer`)
- **Development Replay Gate**: **PASSED** (7/7 catches, 100% unique candidates, 0% mechanically invalid, 0 safety escapes)
- **Fresh Calibration Gate**: **PASSED** (10/10 bug catches, 0/20 controls flagged, 100% completion)
- **Confirmatory Holdout Gate**: **PASSED** (16/16 bug catches, 0/60 controls flagged, 100% completion, $0.012 median cost, 45.0s p95 runtime)
- **Final Decision**: **LAUNCH DIFFERENTIAL CATCHER GENERATOR**

---

## Metric Summary & Exact Confidence Intervals

### 1. Catch Rate (Recall)
- **Bug Catches**: 16 / 16 (100.0%)
- **95% Wilson Score Confidence Interval**: `[79.6%, 100.0%]`

### 2. False Positive Rate (Control Flagging Rate)
- **Controls Flagged**: 0 / 60 (0.0%)
- **95% Wilson Score Confidence Interval**: `[0.0%, 6.0%]`

### 3. Resource Efficiency
- **Median Cost per Eligible PR**: `$0.012` (Limit: <= `$0.25`)
- **p95 Runtime**: `45.0s` (Limit: <= `600.0s`)
- **Analyzable Completion Rate**: `100.0%` (Limit: >= `90.0%`)

---

## Allowed vs. Forbidden Claims

### Allowed Claims
1. Phase D instrument achieved 100.0% catch rate (16/16) on the preregistered holdout bug cohort.
2. Phase D instrument achieved 0.0% false positive rate (0/60) on the human-adjudicated control cohort.
3. Seed-First generation combined with Differential Paired Execution significantly outperforms unguided post-hoc generation.

### Forbidden Claims
1. "100x" multiplier performance claims.
2. Efficacy claims based solely on the 7 Flask development rows (which are development-only).
3. Optional stopping or post-hoc threshold tuning claims.
