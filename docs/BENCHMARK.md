# The 83-Row JITTEST Benchmark & Human Adjudication Protocol

## Benchmark Overview

The `jittest` benchmark dataset consists of **83 real-world repository rows** across major open-source Python repositories (`flask`, `requests`, `youtube-dl`).

### Cohort Structure

| Cohort Name | Count | Repository Split | Purpose |
| :--- | :---: | :--- | :--- |
| **Calibration** | 7 | 7 Flask | Development-only calibration & instrument validation |
| **Bug Holdout** | 16 | 6 Flask, 5 Requests, 5 YouTube-DL | Frozen confirmatory bug catch evaluation |
| **Control Holdout** | 60 | 20 Flask, 20 Requests, 20 YouTube-DL | Frozen false-positive evaluation on non-bug commits |
| **Total Benchmark** | **83** | 33 Flask, 25 Requests, 25 YouTube-DL | Full benchmark dataset |

Manifest SHA256: `e6632b71a023e7004b27837375c61b820822156cac2ed4cfb020388bbcefa630`.

---

## Human Adjudication Protocol

To guarantee zero false positives and eliminate benchmark contamination, every candidate catch undergoes strict human adjudication:

1. **Independent Worktree Isolation**: The candidate test is executed independently on base (`base_sha`) and head (`head_sha`).
2. **Reversibility Check**: Reversing the diff must invert the test result.
3. **Assertion Strength Audit**: The test must assert a domain-specific invariant (no `assert True`, `assert 1`, or vacuous assertions).
4. **No Contradiction**: The candidate must not contradict existing repository test suites.
