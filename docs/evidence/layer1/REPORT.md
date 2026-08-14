# Layer-1 Verifier Sweep Report

- **Target Cohort**: Frozen 83-Row Benchmark Cohort (`phase-c-benchmark-manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 118.8s

## Headline Metrics

- **Controls executed**: 13/60 — false proofs: 0/13 (47 controls inconclusive: historical environment decay; an unexecuted control cannot false-fire)
- **Bug rows executed**: 11/23 — proven_catch: 5/11 (5/23 of full cohort)
- **Coverage**: 83/83 rows attempted with signed receipts; 24/83 (29%) executed to definitive verdicts; 59/83 refused loudly (inconclusive)

59 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with `tool_dirty=true` (pre-commit sweep snapshot captured at runtime prior to final commit).
- **Sandbox Backend**: Ran with sandbox backend `"none"` (benign frozen cohort; outside PRs default to sandbox mode).
- **Receipt Cryptographic Validity**: 83/83 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 23 | 11 (47.8%) | 12 (52.2%) | 5 `proven_catch` (Flask 01–05), 4 `refuted` (latent failure on base), 2 `non_discriminating` (passed on head) |
| **Control Rows** | 60 | 13 (21.7%) | 47 (78.3%) | 0 false proofs, 13 `refuted` (correctly rejected as latent failures on base) |
| **Total Cohort** | **83** | **24 (28.9%)** | **59 (71.1%)** | **5 proven catches, 0 false proofs, 59 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage | Interpretation |
| :--- | :--- | :--- | :--- |
| `catching` | 5 | 6.0% | Test passed on base commit and failed on head commit (`proven_catch`). |
| `head_failed_base_failed_latent` | 17 | 20.5% | Test failed on head but also failed on base (`refuted`). |
| `head_passed` | 2 | 2.4% | Test passed on head (`non_discriminating`). |
| `env_setup_failed` | 15 | 18.1% | Historical revision dependencies failed isolated virtualenv build (`inconclusive`). |
| `head_uncollectable` | 44 | 53.0% | Test file syntax/imports could not be collected in runner environment (`inconclusive`). |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1/<row_id>_evidence.json
```

Or re-run the full layer-1 sweep:
```bash
python scripts/run_layer1_sweep.py
```
