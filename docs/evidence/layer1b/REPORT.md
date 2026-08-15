# Layer-1 Verifier Sweep Report

- **Target Cohort**: layer1b_modern_cohort (`eval/layer1b_manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 2470.9s

## Headline Metrics

- **Controls executed**: 18/24 — false proofs: 2/18 (6 controls inconclusive)
- **Bug rows executed**: 18/30 — proven_catch: 4/18 (4/30 of full cohort)
- **Coverage**: 54/54 rows attempted with signed receipts; 36/54 (66.7%) executed to definitive verdicts; 18/54 refused loudly (inconclusive)

18 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with `tool_dirty=True`.
- **Sandbox Backend**: Ran with sandbox backend `"none"` (--no-sandbox; candidate tests ran unconfined). Outside PRs default to sandbox mode.
- **Receipt Cryptographic Validity**: 54/54 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 30 | 18 (60.0%) | 12 (40.0%) | 4 `proven_catch`, 13 `refuted`, 1 `non_discriminating` |
| **Control Rows** | 24 | 18 (75.0%) | 6 (25.0%) | 2 false proofs, 8 `refuted`, 8 `non_discriminating` |
| **Total Cohort** | **54** | **36 (66.7%)** | **18 (33.3%)** | **4 proven catches, 2 false proofs, 18 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `catching` | 6 | 11.1% |
| `env_setup_failed` | 2 | 3.7% |
| `head_failed_base_failed_latent` | 21 | 38.9% |
| `head_flaky` | 3 | 5.6% |
| `head_passed` | 9 | 16.7% |
| `head_uncollectable_base_broken` | 13 | 24.1% |

## ENV-FIDELITY-1 Delta Table (Audit of Fix Impact)

| Row ID | Kind | Repo | Baseline Disposition | New Disposition | Baseline Verdict | New Verdict | Delta Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bug_flask_01` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_02` | bug | flask | `env_setup_failed` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `env_setup_failed` → `head_failed_base_failed_latent` |
| `bug_flask_03` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_04` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_05` | bug | flask | `env_setup_failed` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `env_setup_failed` → `head_failed_base_failed_latent` |
| `bug_requests_06` | bug | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_requests_07` | bug | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_requests_08` | bug | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_requests_09` | bug | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_requests_10` | bug | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `bug_click_11` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_12` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_13` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_14` | bug | click | `head_failed_base_failed_latent` | `catching` | `refuted` | `proven_catch` | `head_failed_base_failed_latent` → `catching` |
| `bug_click_15` | bug | click | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `bug_httpx_16` | bug | httpx | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_httpx_17` | bug | httpx | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_httpx_18` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_httpx_19` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_httpx_20` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_rich_21` | bug | rich | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_rich_22` | bug | rich | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_rich_23` | bug | rich | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_rich_24` | bug | rich | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_rich_25` | bug | rich | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_pytest_26` | bug | pytest | `head_uncollectable` | `head_flaky` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_flaky` |
| `bug_pytest_27` | bug | pytest | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_pytest_28` | bug | pytest | `head_uncollectable` | `head_flaky` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_flaky` |
| `bug_pytest_29` | bug | pytest | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_pytest_30` | bug | pytest | `head_flaky` | `head_flaky` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_flask_01` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_02` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_03` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_04` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_requests_05` | control | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `ctrl_requests_06` | control | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `ctrl_requests_07` | control | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `ctrl_requests_08` | control | requests | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `ctrl_click_09` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_10` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_11` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_12` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_httpx_13` | control | httpx | `env_setup_failed` | `env_setup_failed` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_httpx_14` | control | httpx | `env_setup_failed` | `env_setup_failed` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_httpx_15` | control | httpx | `env_setup_failed` | `head_passed` | `inconclusive` | `non_discriminating` | `env_setup_failed` → `head_passed` |
| `ctrl_httpx_16` | control | httpx | `head_failed_base_failed_latent` | `head_passed` | `refuted` | `non_discriminating` | `head_failed_base_failed_latent` → `head_passed` |
| `ctrl_rich_17` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_18` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_19` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_20` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_pytest_21` | control | pytest | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |
| `ctrl_pytest_22` | control | pytest | `head_uncollectable` | `catching` | `inconclusive` | `proven_catch` | `head_uncollectable` → `catching` |
| `ctrl_pytest_23` | control | pytest | `env_setup_failed` | `catching` | `inconclusive` | `proven_catch` | `env_setup_failed` → `catching` |
| `ctrl_pytest_24` | control | pytest | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1b/<row_id>_evidence.json
```

Or re-run the full sweep:
```bash
python scripts/run_layer1_sweep.py --manifest eval/layer1b_manifest.json
```
