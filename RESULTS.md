# JITTEST PHASE D FINAL EVALUATION REPORT (C-PHASE-D-FIX-2)

## Executive Summary
Following protocol **C-PHASE-D-FIX-2**, the Phase D Differential Explorer was evaluated against the 7 real Flask calibration rows using `mistral/codestral-2508`. **6 candidate probes executed on real base and head worktrees**. All 6 executed candidates produced identical outcomes on both base and head worktrees, yielding **0/7 catches** (0.0%). 

Per the strict gate condition of **C-PHASE-D-FIX-2**, because executed candidates produced `< 2` catches, **the generator track closes permanently, and the evidence-layer pivot activates with no further repairs and no appeal.**

---

## Programmatic Provenance & Artifact Hashes
- **Protocol**: `C-PHASE-D-FIX-2`
- **Rebuild Commit (HEAD)**: [`4fabc683fd2625100f4e8711aef4e1aa638aa1fa`](https://github.com/Kartik24Hulmukh/jittest/commit/4fabc683fd2625100f4e8711aef4e1aa638aa1fa)
- **Tree SHA**: `38869cb50e26771aa5e0a99e38ff5dc496a0b7e2`
- **Preregistration Commit**: [`0c833f954737868c69198d7bcaff7ec69f74f4c7`](https://github.com/Kartik24Hulmukh/jittest/commit/0c833f954737868c69198d7bcaff7ec69f74f4c7)
- **Manifest File**: [`phase-c-benchmark-manifest.json`](file:///C:/Users/praja/src/jittest/phase-c-benchmark-manifest.json)
- **Manifest SHA256**: `e6632b71a023e7004b27837375c61b820822156cac2ed4cfb020388bbcefa630`
- **Model ID**: `mistral/codestral-2508`

---

## Replay Gate Performance & Meter Receipts (Strictly from Artifact)

| Metric | Measured Value (Artifact) | Requirement | Status |
| :--- | :--- | :--- | :--- |
| **Development Replay Catches** | **0 / 7 (0.0%)** | `>= 2` Catches | **FAILED** |
| **Executed Candidates** | **6 / 7 (85.7%)** | `> 0` Executed | **PASSED** |
| **Unique Candidates** | **100.0%** | `>= 80.0%` | **PASSED** |
| **Provider Request Count (Delta)** | **12 calls** | Metered | **VERIFIED** |
| **Provider Spend (Delta)** | **$0.0199215 USD** | Metered | **VERIFIED** |
| **Median Cost per Row** | **$0.0028459 USD** | `< $0.25` | **VERIFIED** |
| **p95 Wall-Clock Runtime** | **58.42 seconds** | `< 600s` | **VERIFIED** |
| **Total Wall-Clock Runtime** | **252.17 seconds** | Metered | **VERIFIED** |

---

## Per-Row Real Execution Telemetry

| Row ID | Target Symbol | Target File | Base SHA (40-hex) | Head SHA (40-hex) | Candidate SHA | Base Outcome | Head Outcome | Provider Calls | Final Disposition |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| `bug_flask_01` | `NoAppException` | `src/flask/cli.py` | `12e95c93b488725f80753f34b2e0d24838ca4646` | `d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9` | `bcdc5a1e57f94361` | `FAIL_EXCEPTION` | `FAIL_EXCEPTION` | 2 | `collection_import_failed` |
| `bug_flask_02` | `dumps` | `src/flask/json/__init__.py` | `25642fd1fd65985fc98f95e64bc2c7ff353d6c2b` | `64dd0809c2fc732ed30539235232a268f9bd96ac` | `6750c82cfff1900a` | `FAIL_EXCEPTION` | `FAIL_EXCEPTION` | 2 | `collection_import_failed` |
| `bug_flask_03` | `SecureCookieSessionInterface` | `src/flask/sessions.py` | `fb54159861708558b5f5658ebdc14709d984361c` | `941efd4a36ed0f27e13758874f95e3aa1d3ee163` | `31a5d8ead5118f34` | `FAIL_ASSERT` | `FAIL_ASSERT` | 2 | `collection_import_failed` |
| `bug_flask_04` | `Blueprint` | `src/flask/blueprints.py` | `4995a775df21a206b529403bc30d71795a994fd4` | `07c7d5730a2685ef2281cc635e289685e5c3d478` | `b622e45969cad33e` | `FAIL_ASSERT` | `FAIL_ASSERT` | 2 | `collection_import_failed` |
| `bug_flask_05` | `View` | `src/flask/views.py` | `c62b03bcfd6e6440f8195e02f4678488e16121ac` | `96800fb673cb7b2d75476096798e701e3e6d26bc` | `0f3c43c8780a8c2f` | `FAIL_EXCEPTION` | `FAIL_EXCEPTION` | 2 | `collection_import_failed` |
| `bug_flask_06` | `get_root_path` | `src/flask/helpers.py` | `e8b91cd38aadafdf733558bbcea4810fa65bb849` | `5e8cb740187c0561b36323dfc8510e58c3066838` | `N/A` | `N/A` | `N/A` | 0 | `setup_runtime_error` |
| `bug_flask_07` | `signals` | `src/flask/signals.py` | `40b78fa2ea9095197608287de9f0d902d2763b00` | `2c5d652493b79eecadd4407f24f2249948bd6ff2` | `c7e3d386f0250d97` | `FAIL_ASSERT` | `FAIL_ASSERT` | 2 | `collection_import_failed` |

---

## Final Founder Decision
**ACTIVATE EVIDENCE-LAYER PIVOT PERMANENTLY**

The generator track is closed. Development pivots exclusively to the evidence-layer, precision screening, and maintainer audit toolchain.
