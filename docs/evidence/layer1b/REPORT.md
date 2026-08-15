# Layer-1 Verifier Sweep Report

- **Target Cohort**: layer1b_modern_cohort (`eval/layer1b_manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 1629.3s

## Headline Metrics

- **Controls executed**: 13/24 — false proofs: 0/13 (11 controls inconclusive)
- **Bug rows executed**: 15/30 — proven_catch: 3/15 (3/30 of full cohort)
- **Coverage**: 54/54 rows attempted with signed receipts; 28/54 (51.9%) executed to definitive verdicts; 26/54 refused loudly (inconclusive)

26 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with `tool_dirty=true` (pre-commit sweep snapshot captured at runtime prior to final commit).
- **Sandbox Backend**: Ran with sandbox backend `"none"` (benign evaluation cohort; outside PRs default to sandbox mode).
- **Receipt Cryptographic Validity**: 54/54 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 30 | 15 (50.0%) | 15 (50.0%) | 3 `proven_catch`, 11 `refuted`, 1 `non_discriminating` |
| **Control Rows** | 24 | 13 (54.2%) | 11 (45.8%) | 0 false proofs, 9 `refuted`, 4 `non_discriminating` |
| **Total Cohort** | **54** | **28 (51.9%)** | **26 (48.1%)** | **3 proven catches, 0 false proofs, 26 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `catching` | 3 | 5.6% |
| `env_setup_failed` | 6 | 11.1% |
| `head_failed_base_failed_latent` | 20 | 37.0% |
| `head_flaky` | 1 | 1.9% |
| `head_passed` | 5 | 9.3% |
| `head_uncollectable` | 19 | 35.2% |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1b/<row_id>_evidence.json
```

Or re-run the full sweep:
```bash
python scripts/run_layer1_sweep.py --manifest eval/layer1b_manifest.json
```
