# Layer-1 Verifier Sweep Report

- **Target Cohort**: layer1b_modern_cohort (`eval/layer1b_manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 276.3s

## Headline Metrics

- **Controls executed**: 13/24 — false proofs: 0/13 (11 controls inconclusive)
- **Bug rows executed**: 18/30 — proven_catch: 4/18 (4/30 of full cohort)
- **Coverage**: 54/54 rows attempted with signed receipts; 31/54 (57.4%) executed to definitive verdicts; 23/54 refused loudly (inconclusive)

23 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with clean working tree (`tool_dirty=false`).
- **Sandbox Backend**: Ran with sandbox backend `"none"` (--no-sandbox; candidate tests ran unconfined). Outside PRs default to sandbox mode.
- **Receipt Cryptographic Validity**: 54/54 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 30 | 18 (60.0%) | 12 (40.0%) | 4 `proven_catch`, 13 `refuted`, 1 `non_discriminating` |
| **Control Rows** | 24 | 13 (54.2%) | 11 (45.8%) | 0 false proofs, 8 `refuted`, 5 `non_discriminating` |
| **Total Cohort** | **54** | **31 (57.4%)** | **23 (42.6%)** | **4 proven catches, 0 false proofs, 23 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `catching` | 4 | 7.4% |
| `env_setup_failed` | 11 | 20.4% |
| `head_failed_base_failed_latent` | 21 | 38.9% |
| `head_passed` | 6 | 11.1% |
| `head_uncollectable_base_broken` | 12 | 22.2% |

## ENV-FIDELITY-1 Delta Table (Audit of Fix Impact)

| Row ID | Kind | Repo | Baseline Disposition | New Disposition | Baseline Verdict | New Verdict | Delta Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bug_flask_01` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_02` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_03` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_04` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_flask_05` | bug | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_requests_06` | bug | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_requests_07` | bug | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_requests_08` | bug | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_requests_09` | bug | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_requests_10` | bug | requests | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_11` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_12` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_13` | bug | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_click_14` | bug | click | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_click_15` | bug | click | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `bug_httpx_16` | bug | httpx | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_httpx_17` | bug | httpx | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_httpx_18` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_httpx_19` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_httpx_20` | bug | httpx | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_rich_21` | bug | rich | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_rich_22` | bug | rich | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `bug_rich_23` | bug | rich | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_rich_24` | bug | rich | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_rich_25` | bug | rich | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `bug_pytest_26` | bug | pytest | `head_flaky` | `env_setup_failed` | `inconclusive` | `inconclusive` | `head_flaky` → `env_setup_failed` |
| `bug_pytest_27` | bug | pytest | `head_uncollectable_base_broken` | `env_setup_failed` | `inconclusive` | `inconclusive` | `head_uncollectable_base_broken` → `env_setup_failed` |
| `bug_pytest_28` | bug | pytest | `head_flaky` | `env_setup_failed` | `inconclusive` | `inconclusive` | `head_flaky` → `env_setup_failed` |
| `bug_pytest_29` | bug | pytest | `head_uncollectable_base_broken` | `env_setup_failed` | `inconclusive` | `inconclusive` | `head_uncollectable_base_broken` → `env_setup_failed` |
| `bug_pytest_30` | bug | pytest | `head_flaky` | `env_setup_failed` | `inconclusive` | `inconclusive` | `head_flaky` → `env_setup_failed` |
| `ctrl_flask_01` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_02` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_03` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_04` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_requests_05` | control | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_requests_06` | control | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_requests_07` | control | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_requests_08` | control | requests | `head_uncollectable_base_broken` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_click_09` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_10` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_11` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_12` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_httpx_13` | control | httpx | `env_setup_failed` | `env_setup_failed` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_httpx_14` | control | httpx | `env_setup_failed` | `env_setup_failed` | `inconclusive` | `inconclusive` | Unchanged |
| `ctrl_httpx_15` | control | httpx | `head_passed` | `head_uncollectable_base_broken` | `non_discriminating` | `inconclusive` | `head_passed` → `head_uncollectable_base_broken` |
| `ctrl_httpx_16` | control | httpx | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_17` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_18` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_19` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_rich_20` | control | rich | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `ctrl_pytest_21` | control | pytest | `head_passed` | `env_setup_failed` | `non_discriminating` | `inconclusive` | `head_passed` → `env_setup_failed` |
| `ctrl_pytest_22` | control | pytest | `catching` | `env_setup_failed` | `proven_catch` | `inconclusive` | `catching` → `env_setup_failed` |
| `ctrl_pytest_23` | control | pytest | `catching` | `env_setup_failed` | `proven_catch` | `inconclusive` | `catching` → `env_setup_failed` |
| `ctrl_pytest_24` | control | pytest | `head_passed` | `env_setup_failed` | `non_discriminating` | `inconclusive` | `head_passed` → `env_setup_failed` |

## Recompute Command

To recompute and verify any individual evidence receipt:
```bash
jittest verify-receipt docs/evidence/layer1b/<row_id>_evidence.json
```

Or re-run the full sweep:
```bash
python scripts/run_layer1_sweep.py --manifest eval/layer1b_manifest.json
```
