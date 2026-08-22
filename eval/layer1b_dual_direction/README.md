# Layer-1B Dual-Direction Internal Evaluation (54 rows, self-selected)

> This is an internal self-selected evaluation, NOT a benchmark submission.
> No external party has re-executed these results.

## Overview

This directory contains the internal evaluation artifacts for **jittest v0.3.5** across the 54 self-selected Layer-1B dataset instances.

jittest is a differential test execution verifier and gate for pull requests with Ed25519-signed cryptographic receipts.

## Evaluation Methodology & Dual-Direction Evaluation

Unlike non-differential test evaluation, jittest enforces **differential execution across both git states**:

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
- **Verdict**: `inconclusive`

## Package Contents
- `results.jsonl`: Formatted evaluation results for all 54 Layer-1B rows.
- `traces/`: Structured execution traces and receipts for each evaluated instance.
