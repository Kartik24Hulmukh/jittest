# Evidence & Verification Receipts

This directory contains cryptographically signed evidence JSON artifacts produced by `jittest verify` (and `jittest/verify-action`).

## Real Public E2E Plumbing Proof (`docs/evidence/pr/flask_pr_evidence.json`)

> [!NOTE]
> `flask_pr_evidence.json` is an **end-to-end plumbing proof** demonstrating real PR resolution on public repositories (`pallets/flask` PR #6133).
> - **Verdict**: `refuted` (`head_failed_base_failed_latent`)
> - **Purpose**: Proves full CLI and resolution pipeline execution (`jittest verify --repo pallets/flask --pr 6133 --test tests/test_basic.py`) against public git commits.

## Four-Quadrant Proof Set (`docs/evidence/quadrants/`)

The four-quadrant demo artifacts showcase signed evidence for all potential test verdict outcomes:

1. **`proven_catch_evidence.json`**:
   - Verdict: `proven_catch` (`catching`)
   - Recompute Command: `jittest verify-receipt docs/evidence/quadrants/proven_catch_evidence.json`

2. **`refuted_evidence.json`**:
   - Verdict: `refuted` (`head_failed_base_failed_latent`)
   - Recompute Command: `jittest verify-receipt docs/evidence/quadrants/refuted_evidence.json`

3. **`non_discriminating_evidence.json`**:
   - Verdict: `non_discriminating` (`head_passed`)
   - Recompute Command: `jittest verify-receipt docs/evidence/quadrants/non_discriminating_evidence.json`

4. **`inconclusive_evidence.json`**:
   - Verdict: `inconclusive` (`head_uncollectable`)
   - Recompute Command: `jittest verify-receipt docs/evidence/quadrants/inconclusive_evidence.json`

## How to Verify Receipts

To independently verify the authenticity and integrity of any receipt:
```bash
jittest verify-receipt docs/evidence/quadrants/proven_catch_evidence.json
```
or run the offline Python verification snippet documented in [`docs/KEYS.md`](../KEYS.md).

## Layer 1 Historical Evaluation Sweep (`docs/evidence/layer1b/`)

> [!NOTE]
> `docs/evidence/layer1b/` contains frozen historical evaluation receipts. Their cryptographic payload signatures cover the exact original runner environment paths (`/home/runner/...`). They are intentionally preserved as immutable evaluation records and are explicitly exempted from repository path linters so their signatures remain valid.
