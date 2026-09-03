# Antigravity Hardening Audit & Completion Ledger

## 1. Executive Summary & Verdict

This engagement audited the JitTest repository against the 2026-09-03 decision pack, verified each defect directly against the baseline (`1412238a830036728cb15b9fd89d9810528d235e`), implemented surgical fixes across staged PRs, restored the `action.yml` default to `required`, enforced fork-safety in `action.py`, and updated the project defect ledger with honest boundary classifications:
- **D1**: **WAIVED via Option D** (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests).
- **D2**: **MITIGATED** (secrets scrubbed via `_scrubbed_installer_env`, but host `pip` still runs unconfined PR files before sandbox; not claimed fork-safe).
- **D9**: **OPEN** (no real-daemon dependency-bearing isolation proof; documenting Option D does not close an operational gate).

**Explicit Release Confirmation**: Version `0.3.5` was **NOT** published. No Git tags were pushed, no GitHub releases were published, and no packages were uploaded to PyPI. The public PyPI release remains pinned at `v0.3.4`.

### Allowed Public Sentence
> **"JitTest on SHA e296c71f17f828d7ec683115542eeb7eb055ebab is an alpha advisory verifier for PR-modified Python tests. Receipts are signed. Isolation is Option D (stdlib-only in containers; dependency-bearing tests refuse). It is not a production merge gate. pip install jittest is still 0.3.4."**

---

## 2. Merged PRs & Exact SHAs

| Wave / Fix | Pull Request | Merge Commit SHA | Scope | CI Check Count |
|---|---|---|---|---|
| **Baseline** | — | `1412238a830036728cb15b9fd89d9810528d235e` | Pre-hardening baseline | — |
| **Wave 1** | [PR #167](https://github.com/Kartik24Hulmukh/jittest/pull/167) | `79856bbc44480cd3edcfddabb5bb71d5eb8d450f` | D3 (Path containment), D4 (Signer prefix floor), D6 (Evidence collision) | 26 / 26 Green |
| **Wave 2** | [PR #168](https://github.com/Kartik24Hulmukh/jittest/pull/168) | `6cb695c43e13fc08a09b3a66a649ff0cfad3f587` | D7 (6-verdict schema conformance), D5 (Receipt semantics & provenance) | 26 / 26 Green |
| **Wave 3** | [PR #169](https://github.com/Kartik24Hulmukh/jittest/pull/169) | `e27370b33b3e5263f9cef74b5445caa22945fadd` | D1 (Option D refusal), D2 (Sanitized installer env + Job F), D8 (Action defaults) | 26 / 26 Green |
| **Wave 4** | [PR #170](https://github.com/Kartik24Hulmukh/jittest/pull/170) | `e296c71f17f828d7ec683115542eeb7eb055ebab` | D9 (Container daemon status & Option D contract docs), Honest README boundaries | 26 / 26 Green |
| **Follow-up** | [PR #171](https://github.com/Kartik24Hulmukh/jittest/pull/171) | `b528185e01c773614905c00f747a11aa9920d250` | Restore `action.yml` default to `required`; enforce fork safety in `action.py`; align D1/D2/D9 statuses | 26 / 26 Green |

---

## 3. Defect Ledger & Independent Ruling

| Defect ID | Title | Severity | Status | Enforcement Mechanism & Test Proof |
|---|---|---|---|---|
| **D1** | Required Docker/Podman discards venv | **P0** | **WAIVED (Option D)** | Waived via Option D (honest refusal for dependency-bearing repos; stdlib-only in container; not a full fix for Flask/Django/requests). When Docker/Podman container mode is active, any dependency-bearing test or repository raises `VerifyRefusalError("isolation contract cannot import project dependencies in container mode")`. Tests: `test_container_mode_refuses_dependency_bearing_repo`, `test_container_mode_allows_stdlib_only_repo` in `tests/test_wave3_isolation.py`. |
| **D2** | Host provisioning runs untrusted files before sandbox | **P0** | **MITIGATED** | Mitigated (secrets scrubbed via `_scrubbed_installer_env`, but host `pip` still runs unconfined PR files before sandbox; not claimed fork-safe). Strips sensitive environment keys (`TOKEN`, `SECRET`, `KEY`, `PASS`, `AUTH`, `CRED`, `BEARER`) before package installation. Hostile fixture proves `setup.py` cannot harvest `GITHUB_TOKEN`. Tests: `test_scrubbed_env_strips_sensitive_keys`, `test_job_f_hostile_setup_does_not_see_github_token` in `tests/test_wave3_isolation.py`. |
| **D3** | Symlink / out-of-repo test path is read then signed | **P0** | **CLOSED** | Path resolution in `src/jittest/verify.py` refuses non-regular files and paths outside repo with exit code 2 *without* calling `read_text()` or generating receipts. Removed `Path(test_path.name)` fallback. Tests: `test_d3_path_containment_refuses_outside_symlink`, `test_d3_path_containment_refuses_directory` in `tests/test_wave1_trust_path.py`. |
| **D4** | Signer prefix floor missing (short prefixes accepted) | **P1** | **CLOSED** | `_matches_signer()` in `src/jittest/receipt.py` requires exactly 64 hex chars for full public keys or minimum 16 hex chars for fingerprints. Shorter inputs return `SIGNER_INVALID_FORMAT` / not trusted. Tests: `test_d4_signer_prefix_floor_rejects_short_prefix`, `test_d4_signer_prefix_floor_accepts_valid_16char_prefix` in `tests/test_wave1_trust_path.py`. |
| **D5** | `verify_receipt` validates signature but not semantics | **P1** | **CLOSED** | Enhanced `verify_receipt()` in `src/jittest/receipt.py` and CLI to validate schema conformance, tool invariants, verdict enum consistency, and provenance flags (`--expected-base`, `--expected-head`, `--expected-test-sha256`, `--expected-repo`). Returns structured `ReceiptVerificationResult`. Tests: `test_d5_verify_receipt_provenance_mismatch`, `test_d5_verify_receipt_invariant_checks` in `tests/test_wave2_schema_semantics.py`. |
| **D6** | Evidence artifact filename collision | **P1** | **CLOSED** | Changed artifact naming in `src/jittest/action.py` and `src/jittest/cli.py` to `evidence-{stem}-{sha256(posix_relpath)[:12]}.json`. Confirmed distinct artifact files for duplicate stem paths. Test: `test_d6_unique_evidence_names_different_paths` in `tests/test_wave1_trust_path.py`. |
| **D7** | Schema / source verdict agreement | **P2** | **CLOSED** | Updated `docs/SCHEMA.md`, `README.md`, and `src/jittest/receipt.py` to recognize all 6 canonical verdicts (`proven_catch`, `reproduction_catch`, `collection_catch`, `refuted`, `non_discriminating`, `inconclusive`). Replaced deprecated `public_key` with `verifying_key`. Test: `test_d7_schema_conformance_all_verdicts` in `tests/test_wave2_schema_semantics.py`. |
| **D8** | Action default and artifact handling skew | Release blocker | **CLOSED** | In `action.yml`, restored default `sandbox-mode: 'required'`. In `action.py`, preserved fork safety by ensuring fork and unknown contexts always resolve to `required` (preventing downgrade). Maintained `if-no-files-found: warn`. Tests: `test_action_yaml_defaults` in `tests/test_wave3_isolation.py`, `test_run_action_sandbox_threading` in `tests/test_action.py`. |
| **D9** | Real container isolation unproven in CI | Operational gate | **OPEN** | Open (no real-daemon dependency-bearing isolation proof). Option D documented in `docs/ISOLATION.md`. Container isolation is validated only for stdlib-only tests and explicit refusal of dependency-bearing suites; full container-native provisioning (Option B/C) remains open. |
| **D10** | Action only verifies changed test files | Positioning | **DOCUMENTED** | Clarified in documentation and README that JitTest Mode A evaluates PR-modified Python tests for discrimination, rather than claiming automated test generation or full regression coverage. |

---

## 4. Isolation Contract Details (Option D)

- **Selected Contract**: Option D (Restricted support).
- **Behavior**:
  - Purely stdlib-only test suites run confined inside Docker or Podman containers (`--network none`, read-only worktree mount).
  - Repositories declaring external dependencies (`requirements.txt`, PEP 621 dependencies, lockfiles) refuse execution with:
    `jittest verify: refused - isolation contract cannot import project dependencies in container mode`
  - Zero false positives or bogus executions resulting from missing project dependencies.
- **Honest Assessment**: Green checks on Option D prove stdlib-only container execution + honest refusal of dependency-bearing repos + advisory comments. This provides a safer alpha verifier, but is not a production fix for dependency-bearing repos (Flask/Django/requests).
- **Job D-deps Test Proof**: `test_container_mode_refuses_dependency_bearing_repo` verifies that dependency-bearing repositories trigger an immediate, clean refusal.

---

## 5. Check IDs from Prior Waves

### PR #169 (Wave 3 Isolation & Sanitization) — Run 33768513821 (All 26 Passed)
- `test (windows-latest, 3.12)`: 100692861381
- `test (windows-latest, 3.11)`: 100692861369
- `test (windows-latest, 3.13)`: 100692861367
- `test (ubuntu-latest, 3.12)`: 100692861340
- `test (ubuntu-latest, 3.13)`: 100692861341
- `test (ubuntu-latest, 3.11)`: 100692861123
- `test (macos-latest, 3.12)`: 100692861532
- `test (macos-latest, 3.11)`: 100692861470
- `test (macos-latest, 3.13)`: 100692861364
- `lint`: 100692861465
- `build`: 100692861482
- `mypy-safety`: 100692861385
- `dogfood`: 100692861392
- `consumer_action_e2e`: 100692861227
- `ci`: 100698683686
- `Analyze (python)`: 100692437170
- `Analyze (actions)`: 100692437605
- `catching-tests`: 100692436159
- `verify-pr`: 100692437793
- `check-drift`: 100692437860, 100692412216
- `install (3.11)`: 100692412622
- `install (3.12)`: 100692412714
- `install (3.13)`: 100692412409

### PR #170 (Wave 4 Docs & Contract) — Run 33771675696 (All 26 Passed)
- `test (windows-latest, 3.12)`: 100703593707
- `test (windows-latest, 3.11)`: 100703593723
- `test (windows-latest, 3.13)`: 100703593860
- `test (ubuntu-latest, 3.12)`: 100703593943
- `test (ubuntu-latest, 3.13)`: 100703593869
- `test (ubuntu-latest, 3.11)`: 100703594060
- `test (macos-latest, 3.12)`: 100703593965
- `test (macos-latest, 3.11)`: 100703593709
- `test (macos-latest, 3.13)`: 100703593810
- `lint`: 100703593876
- `build`: 100703593891
- `mypy-safety`: 100703593447
- `dogfood`: 100703594045
- `consumer_action_e2e`: 100703593797
- `ci`: 100709119040
- `Analyze (python)`: 100703184098
- `Analyze (actions)`: 100703184579
- `catching-tests`: 100703184468
- `verify-pr`: 100703185128
- `check-drift`: 100703185772, 100703161271
- `install (3.11)`: 100703160189
- `install (3.12)`: 100703159807
- `install (3.13)`: 100703160375

### PR #171 (Action Default & Defect Alignment) — Run 33779062651 (All 26 Passed)
- `test (windows-latest, 3.12)`: 100727960305
- `test (windows-latest, 3.11)`: 100727960753
- `test (windows-latest, 3.13)`: 100727960598
- `test (ubuntu-latest, 3.12)`: 100727960943
- `test (ubuntu-latest, 3.13)`: 100727960618
- `test (ubuntu-latest, 3.11)`: 100727960627
- `test (macos-latest, 3.12)`: 100727960506
- `test (macos-latest, 3.11)`: 100727961722
- `test (macos-latest, 3.13)`: 100727960817
- `lint`: 100727960426
- `build`: 100727960684
- `mypy-safety`: 100727960555
- `dogfood`: 100727960106
- `consumer_action_e2e`: 100727960584
- `ci`: 100733731955
- `Analyze (python)`: 100727958104
- `Analyze (actions)`: 100727957880
- `catching-tests`: 100727959651
- `verify-pr`: 100727959110
- `check-drift`: 100727959485, 100727897654
- `install (3.11)`: 100727898478
- `install (3.12)`: 100727898414
- `install (3.13)`: 100727897924

---

## 6. Remaining Boundaries & Explicit Non-Claims

1. **Host Provisioning Boundary (D2 — Mitigated)**:
   - `pip` / `uv` dependency installation runs on the host runner before candidate test execution is container-wrapped.
   - Hostile `setup.py` hooks cannot harvest credentials (due to `_scrubbed_installer_env`), but untrusted forks must not be claimed fully safe from malicious build-time execution until Option B (in-container provisioning) is implemented.
2. **Docker Isolation Scope (D1 — Waived, D9 — Open)**:
   - Docker/Podman isolation supports stdlib-only tests; dependency-bearing projects refuse cleanly.
   - Real container daemon isolation for dependency-bearing suites (Flask/Django/requests) is unproven and open.
3. **Action Sandbox Default & Fork Resolution (D8 — Closed)**:
   - Default `sandbox-mode` in `action.yml` is `required`.
   - `action.py` ensures that fork and unknown contexts always resolve to `required`, preventing downgrades to unconfined execution.
4. **Advisory Verifier vs Merge Gate**:
   - Mode A verifier is advisory. It does not block CI builds unless `policy: strict` or `policy: block-on-refusal` is explicitly configured.
5. **Version & Distribution**:
   - The PyPI release is `0.3.4`. Version `0.3.5` on `main` is an unpublished release candidate.
