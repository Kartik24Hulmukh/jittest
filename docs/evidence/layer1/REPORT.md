# Layer-1 Verifier Sweep Report

- **Target Cohort**: Frozen 83-Row Benchmark Cohort (`phase-c-benchmark-manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **Total Rows Evaluated**: 83 / 83 (100.0%)
- **Catch-Proof Rate (Bugs)**: **5/23 (21.7%)**
- **False-Proof Rate (Controls)**: **0/60 (0.0%)**
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 118.8s

## Verdict & Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `catching` | 5 | 6.0% |
| `env_setup_failed` | 15 | 18.1% |
| `head_failed_base_failed_latent` | 17 | 20.5% |
| `head_passed` | 2 | 2.4% |
| `head_uncollectable` | 44 | 53.0% |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1/<row_id>_evidence.json
```

Or re-run the full layer-1 sweep:
```bash
python scripts/run_layer1_sweep.py
```
