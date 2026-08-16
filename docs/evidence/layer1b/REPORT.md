# Layer-1 Verifier Sweep Report (Run 4)

## Provenance and errata

- **CI Verification Run**: Produced by green CI run [https://github.com/Kartik24Hulmukh/jittest/actions/runs/31941524988](https://github.com/Kartik24Hulmukh/jittest/actions/runs/31941524988) with conclusion `success`.
- **CI Artifact**: `layer1b-evidence-run4` with digest `sha256:5092ce538eefee6470150421773c050843fd197159db7f41428fddce993278e1`.
- **CI Runner Environment**: `ubuntu-latest`, 2 workers.
- **Errata**: The Run-2 delta table's baseline column was manually authored and has been superseded by the machine-diffed delta table generated directly from git history; additionally, the run-1->run-3 delta comparison skipped run 2.
- **Coverage (Rows Attempted)**: 54/54 (100.0%) rows attempted with signed receipts; 25/54 (46.3%) executed to definitive verdicts; 29/54 (53.7%) refused loudly (inconclusive).
- **Coverage (Base Reproduced)**: 5/30 (16.7%) bug rows reproduced expected passing behavior on base commit.
- **Execution Timing**: Total wall-clock time 1772.0s (summed row execution time 3516.7s across 2 workers).

---

- **Target Cohort**: layer1b_modern_cohort (`eval/layer1b_manifest.json`)
- **Evaluation Mode**: Layer-1 Differential Execution Verification (Zero LLM Generation)
- **LLM Provider Cost**: **$0.00**
- **Total Wall-Clock Time**: 1772.0s (Summed Row Time: 3516.7s across 2 parallel workers)


> [!NOTE]
> **Errata**: The Run-2 delta table's baseline column was manually authored and has been superseded by the machine-diffed delta table generated directly from git history.

> [!NOTE]
> **Repository Support**: `requests` is marked unsupported due to external live HTTP test server dependencies (`pytest-httpbin` / live network daemons). Its 9 rows are reported honestly as inconclusive (`base_reproduction_failed` / `head_uncollectable`).

## Headline Metrics

- **Controls executed**: 20/24 — false proofs: 0/20 (4 controls inconclusive)
- **Bug rows executed**: 5/30 — proven_catch: 3/5 (behavioral), collection_catch: 0/5 (collection)
- **Base Reproduction Rate**: 5/30 (16.7%) of bug rows reproduced expected passing behavior on base commit
- **Coverage**: 25/54 (46.3%) executed to definitive verdicts; 29/54 refused loudly (inconclusive)
- **Attempt Rate**: 54/54 (100.0%) attempted with signed receipts
- **Execution Timeouts**: 0 timeout classes observed during sweep execution.

29 signed refusals are the trust story: jittest does not manufacture verdicts when environments cannot be built.

## Execution Provenance & Environment Notes

- **Provenance Dirty State**: Receipts ran with clean working tree (`tool_dirty=false`).
- **Tool Commit SHA**: `c6a44ecca73c37a9b208680f2ed316ef27ea2199`
- **Sandbox Backend**: Ran with sandbox backend `"none"` (--no-sandbox; candidate tests ran unconfined). Outside PRs default to sandbox mode.
- **Receipt Cryptographic Validity**: 54/54 signed Ed25519 receipts valid.

## Per-Cohort Breakdown

| Cohort | Total Rows | Executed to Definitive Verdict | Inconclusive (Refused) | Detailed Results |
| :--- | :--- | :--- | :--- | :--- |
| **Bug Rows** | 30 | 5 (16.7%) | 25 (83.3%) | 3 `proven_catch` (behavioral), 0 `collection_catch`, 0 `refuted`, 2 `non_discriminating` |
| **Control Rows** | 24 | 20 (83.3%) | 4 (16.7%) | 0 false proofs, 11 `refuted`, 9 `non_discriminating` |
| **Total Cohort** | **54** | **25 (46.3%)** | **29 (53.7%)** | **3 proven catches, 0 collection catches, 0 false proofs, 29 signed refusals** |

## Full Disposition Breakdown

| Disposition | Count | Percentage |
| :--- | :--- | :--- |
| `base_reproduction_failed` | 25 | 46.3% |
| `catching` | 3 | 5.6% |
| `head_failed_base_failed_latent` | 11 | 20.4% |
| `head_passed` | 11 | 20.4% |
| `head_uncollectable_base_broken` | 4 | 7.4% |

## Machine-Diffed Delta Table (Baseline @9c6320df vs Current @c6a44ecc)

| Row ID | Kind | Repo | Baseline Disp (`@9c6320df`) | New Disp (`@c6a44ecc`) | Baseline Verdict (`@9c6320df`) | New Verdict (`@c6a44ecc`) | Delta Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `bug_flask_01` | bug | flask | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_flask_02` | bug | flask | `env_setup_failed` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `env_setup_failed` → `base_reproduction_failed` |
| `bug_flask_03` | bug | flask | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_flask_04` | bug | flask | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_flask_05` | bug | flask | `env_setup_failed` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `env_setup_failed` → `base_reproduction_failed` |
| `bug_requests_06` | bug | requests | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_requests_07` | bug | requests | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_requests_08` | bug | requests | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |
| `bug_requests_09` | bug | requests | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_requests_10` | bug | requests | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_click_11` | bug | click | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_click_12` | bug | click | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_click_13` | bug | click | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_click_14` | bug | click | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_click_15` | bug | click | `head_passed` | `head_passed` | `non_discriminating` | `non_discriminating` | Unchanged |
| `bug_httpx_16` | bug | httpx | `catching` | `base_reproduction_failed` | `proven_catch` | `inconclusive` | `catching` → `base_reproduction_failed` |
| `bug_httpx_17` | bug | httpx | `catching` | `base_reproduction_failed` | `proven_catch` | `inconclusive` | `catching` → `base_reproduction_failed` |
| `bug_httpx_18` | bug | httpx | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_httpx_19` | bug | httpx | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_httpx_20` | bug | httpx | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_rich_21` | bug | rich | `catching` | `catching` | `proven_catch` | `proven_catch` | Unchanged |
| `bug_rich_22` | bug | rich | `head_failed_base_failed_latent` | `base_reproduction_failed` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `base_reproduction_failed` |
| `bug_rich_23` | bug | rich | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_rich_24` | bug | rich | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_rich_25` | bug | rich | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_pytest_26` | bug | pytest | `head_uncollectable` | `catching` | `inconclusive` | `proven_catch` | `head_uncollectable` → `catching` |
| `bug_pytest_27` | bug | pytest | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_pytest_28` | bug | pytest | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_pytest_29` | bug | pytest | `head_uncollectable` | `base_reproduction_failed` | `inconclusive` | `inconclusive` | `head_uncollectable` → `base_reproduction_failed` |
| `bug_pytest_30` | bug | pytest | `head_flaky` | `catching` | `inconclusive` | `proven_catch` | `head_flaky` → `catching` |
| `ctrl_flask_01` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_02` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_03` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_flask_04` | control | flask | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_requests_05` | control | requests | `head_uncollectable` | `head_passed` | `inconclusive` | `non_discriminating` | `head_uncollectable` → `head_passed` |
| `ctrl_requests_06` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_requests_07` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_requests_08` | control | requests | `head_uncollectable` | `head_failed_base_failed_latent` | `inconclusive` | `refuted` | `head_uncollectable` → `head_failed_base_failed_latent` |
| `ctrl_click_09` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_10` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_11` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_click_12` | control | click | `head_failed_base_failed_latent` | `head_failed_base_failed_latent` | `refuted` | `refuted` | Unchanged |
| `ctrl_httpx_13` | control | httpx | `env_setup_failed` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `env_setup_failed` → `head_uncollectable_base_broken` |
| `ctrl_httpx_14` | control | httpx | `env_setup_failed` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `env_setup_failed` → `head_uncollectable_base_broken` |
| `ctrl_httpx_15` | control | httpx | `env_setup_failed` | `head_uncollectable_base_broken` | `inconclusive` | `inconclusive` | `env_setup_failed` → `head_uncollectable_base_broken` |
| `ctrl_httpx_16` | control | httpx | `head_failed_base_failed_latent` | `head_uncollectable_base_broken` | `refuted` | `inconclusive` | `head_failed_base_failed_latent` → `head_uncollectable_base_broken` |
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
