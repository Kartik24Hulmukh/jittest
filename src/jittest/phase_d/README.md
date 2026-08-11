# [ARCHIVED - EXPERIMENTAL] Phase D Generator Track

> **Status**: Permanently Closed / Archived  
> **Primary Efficacy Result**: 0/7 Catches (0.0%) across 2 valid instrument nulls (Phase C & Phase D).

## Summary & Historical Context

This directory contains the experimental Phase D Differential Explorer (`pipeline_d.py`, `context.py`, `seed.py`, `repair.py`, `differential.py`, `oracle_synthesis.py`).

The design hypothesis rested on seed-first generation, mechanical repair, paired worktree execution, changed-line coverage feedback, and oracle-last synthesis.

### Preregistered Null Results
1. **Phase C Preregistration**: Evaluated on 7 real Flask calibration rows. Result: **0/7 catches**.
2. **Phase D Preregistration (`C-PHASE-D-FIX-2`)**: Rebuilt with real target extraction from git diffs, restored candidate persistence, and probe safety filtering. Result: **6/7 candidates executed** on real base/head worktrees, but all produced identical outcomes on base and head. Result: **0/7 catches**.

### Artifacts & Provenance Receipts
- **Preregistration**: [`phase-d-preregistration.json`](file:///C:/Users/praja/src/jittest/phase-d-preregistration.json)
- **Replay Artifact**: [`phase-d-development-replay.json`](file:///C:/Users/praja/src/jittest/phase-d-development-replay.json)
- **Full Report**: [`RESULTS.md`](file:///C:/Users/praja/src/jittest/RESULTS.md)

This code is preserved intact as a historical credibility asset and reference implementation. All active development has pivoted permanently to the **Evidence Layer (`jittest verify`)**.
