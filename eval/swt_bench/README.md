# SWT-Bench Submission: jittest v0.3.5

## Overview
This directory contains the submission packet for **jittest v0.3.5** on the **SWT-Bench** test generation and verification benchmark.

jittest is a differential test execution verifier and gate for pull requests with Ed25519-signed cryptographic receipts.

## Benchmark Methodology & Honest Dual-Direction Evaluation

Unlike traditional static or non-differential test generators that count passing tests or prompt-engineered assertions without verification, jittest enforces **differential execution across both git states**:

### 1. Reproduction Direction (Fail-to-Pass / Bugfix Proof)
- **State Transition**: `base FAIL (assertion)` $\rightarrow$ `head PASS`
- **Verdict**: `reproduction_catch`
- **Anti-Fabrication Guard (a)**: Base failure must be an assertion failure (`FailureKind.ASSERTION`). Environment, collection, or syntax failures are classified as `base_uncollectable` (verdict: `inconclusive`).
- **Anti-Fabrication Guard (b)**: `PASS_TO_PASS` guard verifies that unmodified existing tests in the repo pass at both base and head commits, ensuring environmental validity.
- **Auditability**: Receipts record `base_failure_kind`.

### 2. Regression Direction (Pass-to-Fail / Regression Proof)
- **State Transition**: `base PASS` $\rightarrow$ `head FAIL`
- **Verdict**: `proven_catch`
- **Claim**: Proves that the code changes on head introduced a behavioral break.

### 3. Non-Discriminating Controls
- **State Transition**: `base PASS` $\rightarrow$ `head PASS`
- **Verdict**: `non_discriminating`
- **Claim**: The candidate test does not discriminate between base and head.

### 4. Refutations & Latent Failures
- **State Transition**: `base FAIL` $\rightarrow$ `head FAIL`
- **Verdict**: `refuted` / `inconclusive`

## Summary of Results (Layer-1B Modern Cohort, 54 rows)

| Metric | Measured Value | Denominator Notes |
| :--- | :--- | :--- |
| **Total Rows Attempted** | 54 / 54 (100%) | Signed Ed25519 receipts generated for all rows |
| **Definitive Verdicts** | 25 / 54 (46.3%) | 29 rows loudly refused (inconclusive / uncollectable) |
| **False Proof Rate (Controls)** | 0 / 20 (0.0%) | 0 false proofs across 20 executed clean controls |
| **Reproduction Catch Rate** | Reported separately | Separated from regression catches |
| **Regression Catch Rate** | Reported separately | Separated from reproduction catches |
| **Zero LLM Generation Cost** | $0.00 | Differential verification execution mode |

## Package Contents
- `predictions.jsonl`: Formatted test predictions for all benchmark rows.
- `traces/`: Structured execution traces and receipts for each benchmark instance.
