# Layer-1 Verifier Sweep Report

- **Target Cohort**: layer1b_modern_cohort (`eval/layer1b_manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 496.2s (Summed Row Time: 3768.9s across 8 parallel workers)
- **Public CI Run URL**: [https://github.com/Kartik24Hulmukh/jittest/actions/runs/31936309719](https://github.com/Kartik24Hulmukh/jittest/actions/runs/31936309719)

## Headline Metrics

- **Controls executed**: 21/24 — false proofs: 0/21 (3 controls inconclusive)
- **Bug rows executed**: 25/30 — proven_catch: 6/25 (behavioral), collection_catch: 0/25 (collection)
- **Coverage**: 54/54 rows attempted with signed receipts; 46/54 (85.2%) executed to definitive verdicts; 8/54 refused loudly (inconclusive)

8 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with clean working tree (`tool_dirty=false`).
- **Tool Commit SHA**: `06354da20ba0d4f25334a0a4c490a46d33632760`
- **Sandbox Backend**: Ran with sandbox backend `"none"` (--no-sandbox; candidate tests ran unconfined). Outside PRs default to sandbox mode.
- **Receipt Cryptographic Validity**: 54/54 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 30 | 25 (83.3%) | 5 (16.7%) | 6 `proven_catch` (behavioral), 0 `collection_catch`, 18 `refuted`, 1 `non_discriminating` |
| **Control Rows** | 24 | 21 (87.5%) | 3 (12.5%) | 0 false proofs, 12 `refuted`, 9 `non_discriminating` |
| **Total Cohort** | **54** | **46 (85.2%)** | **8 (14.8%)** | **6 proven catches, 0 collection catches, 0 false proofs, 8 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `catching` | 6 | 11.1% |
| `env_build_timeout` | 1 | 1.9% |
| `env_setup_failed` | 1 | 1.9% |
| `head_failed_base_failed_latent` | 30 | 55.6% |
| `head_passed` | 10 | 18.5% |
| `head_uncollectable_base_broken` | 6 | 11.1% |

## Machine-Diffed Delta Table (Baseline @9c6320df vs Current @06354da2)

| Row ID | Kind | Repo | Baseline Disp (`@9c6320df`) | New Disp (`@06354da2`) | Baseline Verdict (`@9c6320df`) | New Verdict (`@06354da2`) | Delta Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bug_flask_01` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_02` | bug | flask | `env_setup_failed` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `env_setup_failed` → `head_failed_base_failed_latent` |
| `bug_flask_03` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_04` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_05` | bug | flask | `env_setup_failed` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `env_setup_failed` → `head_failed_base_failed_latent` |
| `bug_requests_06` | bug | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `bug_requests_07` | bug | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `bug_requests_08` | bug | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `bug_requests_09` | bug | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
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
| `bug_pytest_26` | bug | pytest | `head_uncollectable` | `catching` | `inconclusive` | `proven_catch` | `head_uncollectable` → `catching` |
| `bug_pytest_27` | bug | pytest | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_pytest_28` | bug | pytest | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `bug_pytest_29` | bug | pytest | `head_uncollectable` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `head_uncollectable` → `head_uncollectable_base_broken` |
| `bug_pytest_30` | bug | pytest | `head_flaky` | `catching` | `inconclusive` | `proven_catch` | `head_flaky` → `catching` |
| `ctrl_flask_01` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_02` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_03` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_04` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_requests_05` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_requests_06` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_requests_07` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_requests_08` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_click_09` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_10` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_11` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_12` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_httpx_13` | control | httpx | `env_setup_failed` | `env_build_timeout` | `inconclusive` | `inconclusive` | `env_setup_failed` → `env_build_timeout` |
| `ctrl_httpx_14` | control | httpx | `env_setup_failed` | `env_setup_failed` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_httpx_15` | control | httpx | `env_setup_failed` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `env_setup_failed` → `head_uncollectable_base_broken` |
| `ctrl_httpx_16` | control | httpx | `head_failed_base_failed_latent` | `head_passed` | `refuted` | `non_discriminating` | `head_failed_base_failed_latent` → `head_passed` |
| `ctrl_rich_17` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_18` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_19` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_20` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_pytest_21` | control | pytest | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |
| `ctrl_pytest_22` | control | pytest | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |
| `ctrl_pytest_23` | control | pytest | `env_setup_failed` | `head_passed` | `inconclusive` | `non_discriminating` | `env_setup_failed` → `head_passed` |
| `ctrl_pytest_24` | control | pytest | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1b/<row_id>_evidence.json
```

Or re-run the full sweep:
```bash
python scripts/run_layer1_sweep.py --manifest eval/layer1b_manifest.json --prev-sha 9c6320df
```
