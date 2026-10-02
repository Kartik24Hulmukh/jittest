# Advisory preview acceptance — prepared, not authorized

**Inspected engineering source snapshot:** `0ebba4770af4cb90d95eb752175645288b9dd1c9` (PR234 merged). **Published package:** `0.4.1`, source `ef08ddbca551f5d3201cc3e839d1995202bb1934`. **Future release:** version, final integrated source SHA, build, artifact hashes, and publication approval are unfilled. A proposal such as `0.4.2rc1` is not a version bump or approval.

The baseline identifies reviewed source, not an assertion that every retained proof used these exact bytes. Existing CI reports and run artifacts must be read with their own checkout/tool SHA. Any integration or version change requires a new candidate identity and exact-head evidence. Published mapping remains [RELEASE-ARTIFACTS.md](RELEASE-ARTIFACTS.md); do not replace it with an engineering snapshot.

## 1. Choose the lane before installing

| Lane | Exact identity | What acceptance means |
| --- | --- | --- |
| Published offline receipt consumer | `jittest==0.4.1`, mapped published wheel | Sample signature/signer verification; legacy sample is unconfined with provenance unchecked. Not fresh execution, activation, or current-source qualification. |
| Repaired source evaluation | Full baseline SHA above | Unpublished PR232 installation/provenance repairs plus PR234 evidence acceptance, release approval, default attempt census and collection screening; still engineering `0.4.1` metadata. |
| Future uploadable candidate | UNFILLED new approved version + integrated SHA + wheel/sdist hashes | Exact artifact and operational acceptance below; no previous candidate automatically qualifies it. |

Use [Quickstart](QUICKSTART.md) for source-pinned installation. The patched composite [action.yml](../action.yml) invokes [scripts/install_action.py](../scripts/install_action.py): remote Action archives are reconciled to their declared repository/ref and installed from identified source. Do not bypass it with a consumer-repository SHA, mutable `main`, guessed archive identity, or an improvised pip fallback. Only real `action.yml` inputs are valid; there is no `runtime-image` or whole-job-timeout Action input.

The snapshot above is deliberately immutable; it is not a claim that every later commit or published package is qualified. [Post-merge CI](https://github.com/Kartik24Hulmukh/jittest/actions/runs/36782837751) passed on that exact SHA. The retained [Option C proof](https://github.com/Kartik24Hulmukh/jittest/actions/runs/36780912909) and [consumer artifact proof](https://github.com/Kartik24Hulmukh/jittest/actions/runs/36780912972) used PR234 candidate `404885c41e4fd2f1865e1f6c7854d3c8ba6ce395`; its tree matches the snapshot, but the separately built wheel hashes differ with source provenance. Do not call those earlier wheels the snapshot wheel or reuse them for release approval. Issue #73 remains open for independent evidence.

## 2. Operator prerequisites — stop when unfilled

- **Authority:** named operator/reviewer, allowed runner/repository/runtime and artifact retention; separate explicit permission for source changes, execution, tags, upload, announcement, outreach, and spending. None is inferred from merge automation.
- **Runtime:** approved real registry digest, platform/Python/dependency inventory, trusted build provenance and working Docker/Podman daemon. Select from trusted BASE configuration or a deliberate operator override, not HEAD. Example digests in [RUNTIME-IMAGES.md](RUNTIME-IMAGES.md) are placeholders. No arbitrary PR Dockerfile builds or candidate package installs on the host; no unconfined fallback for untrusted code.
- **Signer:** independently obtained expected public key/allowlist, named custodian, trusted delivery channel, scope, rotation/revocation. Receipt-embedded keys cannot establish trust. Project signer, public deterministic fixture signer, partner signer and PyPI OIDC identity are different roles. Never put private key material or credentials in these forms, repo, logs, or candidate mounts. See [KEYS.md](KEYS.md).
- **Whole-job limits:** operator-owned finite admission/queue, provisioning, execution, cleanup and total elapsed budgets; unique run/output directories; bounded concurrency and an actual cancellation/cleanup path. `proc.run_bounded` child timeout begins after `Popen` returns; it is not an admission or total-job deadline. The Action's USD `budget` input is not a time limit. Configure an appropriate external workflow/supervisor deadline and record it; a CI timeout alone does not prove complete descendant cleanup or a request-level SLO.
- **Evidence independence:** independently known base/head/test-byte hash/canonical repo and expected signer; use a separate consumer invocation. Action's same-process receipt check does not independently enroll a production signer or attest a daemon. `--require-confined` checks signed metadata, not an external security certification.

## 3. Existing acceptance lanes — reuse, do not fabricate

No workflow is dispatched by this document. Obtain explicit execution/runner authorization first. Do not use paid generator/cohort workflows for verifier activation.

| Existing lane | What to retain/check | What it does not establish |
| --- | --- | --- |
| [.github/workflows/release.yml](../.github/workflows/release.yml), `workflow_dispatch` | Exact checkout, build run/attempt, wheel/sdist + candidate manifest; `check_distributable.py` clean-wheel own-fixture roundtrip and negatives; publish jobs skipped | Publication or real-daemon acceptance. Dispatch stays build/test-only even on a tag. |
| [.github/workflows/option-c-proof.yml](../.github/workflows/option-c-proof.yml) | `registry-live` authoritative pin; actual `installed-wheel` artifact and `prove_installed_option_c.py` output; real paired canaries, BASE/HEAD controls, external consumer and cleanup. Missing daemon or skipped proof is NOT_RUN, not PASS. | Universal isolation, all dependencies/ABIs, all customer repositories or a different release wheel. This workflow builds its own wheel: match recorded hash to the artifact being qualified. |
| [.github/workflows/install-smoke.yml](../.github/workflows/install-smoke.yml) | Python matrix/install discovery and command compatibility | Its generator `doctor`/dry-run is not verifier activation, meaningful paired execution, customer use or confinement proof. |
| Remote pinned Action acceptance | Actual composite installer/entrypoint plus independent receipt verification; declared Action SHA, installed tool SHA, artifact hash, event BASE/HEAD and policy result | A local `uses: ./` rehearsal alone cannot qualify remote-archive installation. |

For final release bytes: actually rebuild the sdist outside Git and compare runtime files/provenance/metadata/entrypoints with the qualified wheel; preserve the original build. Repeat exact-artifact receipt and confinement controls after any source/version change. Never substitute historical fixture counts for real-world evidence.

## 4. Independent receipt acceptance and refusal

Record producer behavior separately from the evidence-check exit. Use externally supplied `--expected-signer`, `--strict-signer`, full `--expected-base`, `--expected-head`, `--expected-test-sha256`, `--expected-repo`, and where execution is required `--require-confined`. Do not bootstrap expected values from the receipt being checked.

Retain known positive controls and wrong-signer, changed-payload, wrong-head, missing provenance and unconfined negatives. A valid signed refusal can be authentic evidence of **no execution**; it is not activation or a meaningful comparison. Missing artifacts remain visible errors. A green advisory job may contain skips/refusals; strict is not conventional block-on-regression policy. Code-only PRs skip automatic changed-test selection.

Separate milestone timestamps: enrollment complete → admission requested/admitted or rejected → provisioning → actual base/head executions → independent receipt check → first meaningful result understood by the operator → any real decision affected. A signature demo, installation, queue admission, refusal or helper-assisted run cannot silently fill the later milestones.

## 5. Unfilled forms and release approval boundary

[Preview approval packet](templates/advisory-preview-approval.json), [founder/operator measurement](templates/advisory-preview-founder-measurement.json), and [customer opportunity record](templates/advisory-preview-customer-opportunity.json) are **ordinary JSON templates, not executable validators or completed records**. Null means unknown/unfilled, never zero or consent. Copy them to approved private storage before adding human identity, repository details or evidence. Do not commit customer data or credentials.

A source/technical integration must finish before the next final artifact SHA exists. Obtain explicit version/channel and docs/source-edit approval separately from publication. Populate exact source/build-run/artifact IDs, wheel/sdist digests, acceptance refs and operational protections, then seek release approval bound to those values. PR234 implemented external exact-byte approval before publication and fresh downstream artifact rechecks; see [RELEASE-APPROVAL.md](RELEASE-APPROVAL.md). Source implementation does not establish hosted reviewer protection, approval-variable custody, or PyPI trusted publishing. Owner-authenticated inspection still found the `pypi` environment unprotected and its approval digest absent. Do not infer publication authorization from green engineering tests.

A matching **tag push** can initiate publication, so do not create/push a tag as a rehearsal. Verify protected `pypi` environment approvers and the actual Trusted Publisher repository/workflow/environment configuration. The merged guard permits floating `v0` only for canonical final `v0.x.y` tag pushes with an explicitly approved effect; prerelease tags cannot advance it. `workflow_dispatch` is nonpublishing, even on a tag. Verify the actual tag resolves to the approved source and the effective external digest covers that exact run, original build attempt, raw manifests and artifact bytes. This document changes neither workflow nor permissions. No new package replaces existing published `0.4.1` bytes.

## 6. Founder stopwatch and consenting customer value

Reuse the attached founder experiment ledger/protocol rather than add a platform. Founder supplies weekly availability, budget/runway constraint, named support owner, one actual review task, today's alternative and an explicit disproof criterion. Historical plans are not commitments. Record stopwatch start/end events and assistance minutes separately for install, runtime/signer enrollment, first meaningful paired result, independent acceptance, and review decision. Missing timing remains unknown.

No outreach or evaluation starts without specific authorization. A customer record additionally needs a named willing owner, written repository/runtime/data-handling scope, approved runner and retention/redaction/opt-out policy. Consent is a human-provided record, never inferred from a public PR, star, fixture or agent council.

Pre-register eligibility (changed Python tests and approved supported runtime), sampling window and cheap comparator: ordinary review/CI plus a minimal base/head pytest script. Counterbalance comparable tasks or record learning effects. Keep founder-assisted and unaided completion separate. Count all opportunities including ineligible, code-only skips, refusals, errors, no execution and missing artifacts.

Report eligibility/all opportunities; paired execution/eligible attempts; independent evidence acceptance/receipts; usefulness/reviewed results with missing reviews; decisions changed/eligible opportunities reviewed. Repeat use requires a later eligible opportunity and an observed second use, not a theoretical intention. No second opportunity is not automatically churn or retention. Payment requires an actual invoice/payment record; semantic precision needs independent adequate-material adjudication, not model silence. Record all indeterminate cases. Signed evidence must demonstrate incremental value beyond the cheap comparator, not just another successful command.

## 7. Five grounded premortems and bounded countermeasures

| Failure | Grounded mechanism | Bounded countermeasure / stop |
| --- | --- | --- |
| Wrong public version/bytes or silent drift | Repaired source still identifies as 0.4.1; previous proofs and future integration have different SHAs/hashes | Distinct approved next version, exact artifact/run approval, pre-upload digest check, no prerelease floating-tag surprise. Stop on mismatch. |
| False assurance from green/signed output | Advisory permits refusals/skips; authenticity is not correctness or independent confinement | Show separate behavior/trust/coverage facts, external expectations and negative controls. Never sell conventional merge safety or zero-FPR. |
| Admission starvation or concurrent output collision | Child timeout excludes queue admission; shared output names can overwrite even with atomic writes | External whole-job/queue limits and unique attempt paths; record queue/service/cleanup separately and preserve rejected/canceled attempts. Reproduce a failure before more source hardening. |
| Runner/key exposure hidden by metadata | Container kernel/binds and same-process consumer are limited trust boundaries | Disposable least-privilege runner, approved digest, keys outside mounts, actual synthetic sentinels and cleanup proof on exact wheel. Missing daemon is NOT_RUN; leak stops execution. |
| Technically valid receipts with no customer value | Automatic selection excludes code-only PRs; founder assistance and cheap paired pytest may explain all apparent benefit | Honest opportunity census, unaided stopwatch task, cheap-baseline comparison, consented observed repeat use and decision change. Stop noncritical expansion when incremental value is absent. |

This is preparation for a bounded advisory preview, not GA, whole-code correctness, adoption, commercial validation, or a 100× reliability/efficacy promise. Keep issue #73 open for genuine human/semantic/cost/value evidence.
