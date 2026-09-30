# GA73 additive reanalysis — 2026-09-30

**Decision: retain mechanical and conditional screening observations; #73 remains open as a GA evidence gate.** No independent labels, total-cost reconciliation, paid sweep, or corpus execution was performed.

## Frozen provenance and reproduction

`baseline-sha256.json` freezes 154 pre-edit evaluation/evidence files at `bf642162a3059b3ec116c2d0db9333892fa6c9f7`. All files under the original `ga73-20260930` directory remain byte-identical. The original `eval/RESULTS.md` hash is retained even though its wording is intentionally corrected. New generated sidecars do not replace the original summaries or reinterpret their legacy names as validated metrics.

```bash
cd /data/jittest
python3 eval/ga73_reanalysis.py --check
/data/venv/bin/python -m pytest tests/test_eval_ga73_reanalysis.py
/data/venv/bin/ruff check eval/ga73_reanalysis.py tests/test_eval_ga73_reanalysis.py
```

To regenerate only the three derived JSON files, omit `--check`. The script reads JSON/XML, verifies every original evidence hash, cross-checks credit sums with scaled integers, and imports no production or corpus modules. It verifies recorded manifest/row applied-head identities, **not a new offline Git-parent audit**. Research basis: the full council-evaluation review and Astra §§6, 11, 18/validation plus strategy-final §§6, 17–18; usability, repeated use, and paid trials remain proposed human/customer gates, not completed evidence.

## Explicit scopes and denominators

Machine-facing `reanalysis.json` carries:

- `qualification_scope: limited_response_and_collection_screening`
- `independent_labels: absent`
- `runner_identity: not_explicitly_archived`
- `suppressed_candidate_review_material: incomplete`
- `cost_scope: received_response_credit_debits_only`

The 25 historical bug attempts retain 22 response-bearing rows, 78 received responses, 16 mechanically caught specimens (64%), 12 report-bearing specimens (48%), and 13 candidate reports. Twenty mechanically catching candidates have **model** assessments: 13 `real_regression`, four `unclear`, three `intended_change`. Fixed-to-buggy reversal is not demonstrated correspondence to the designated benchmark defect.

The 40 selected Click attempts retain 113 responses, zero reports, and 16 mechanically catching candidates on 11 PRs, all suppressed by model assessment (15 `intended_change`, one `unclear`). Only 12/40 PRs have recorded paired pass/fail outcomes. Thus 40/40 response-bearing is not 40 execution-validated PRs. All 101 typed candidate outcomes remain in the custodian ledger; the bug cohort retains all 58 outcomes. Fifteen static exclusions remain in the 55-Python-PR population frame; 20 original no-call proofs remain zero. Legacy `screened_out=55` is a distinct category, not another 55-row frame or the 15 risk skips.

Collection failure is now described over **candidates with any recorded execution outcome**: Click 1/24, bugs 0/38. Click has 23 paired candidate outcomes and one partial/error outcome; bugs have 34 paired and four head-only pass outcomes. Generation declines/safety/parse refusals do not dilute this denominator. This is a conservative archive-defined entry proxy, not a new runner validity gate. No recorded execution means `not_assessed`; both-fail pairs are never semantic successes. The trusted dilution fixture preserves the historical pooled 10/60 counterexample but reports the oracle-entry rate 10/11.

Fourteen of 16 Click catching excerpts mention `_minirunner`; the other two do not identify a runner. Bug rows' declared `runner=pytest` is retained in raw, but executable/version, probe/fallback reason and per-execution runner receipts are absent. No cause or correctness of fallback is inferred.

Conditional zero-report bounds are unchanged: rule-of-three 7.5%, exact one-sided 7.21575245%. Both require an independent common-rate sampling model not demonstrated by this one-project historical frame, and neither is independently labeled FPR.

## Blinded adjudication packet contract

**PUBLIC TEMPLATE — NOT ACTUALLY BLINDED.** This directory and `custodian-key.json` are intended for a public repository. The mapping is public reference material, not restricted or secret custody; anyone can resolve the template IDs to cohorts/model outputs. Field omission demonstrates a proposed review format, not effective blinding. There are no completed human reviews or labels here. Future real adjudication requires a separately prepared private mapping and fresh IDs that are never published before reviewer labels are locked; do not reuse these publicly mapped IDs.

`reviewer-template.json` contains **116 unfilled cases**: 80 population cases (55 Python-changing PRs including static skips, plus all 25 bug attempts) and 36 mechanically catching candidate cases, including every suppressed catch. This is a **template, not a ready-to-adjudicate packet**. Existing archives omit exact candidate bytes and sufficient supported-contract/context material; every case is explicitly `template_only_unadjudicatable_from_retained_archive`. There are no invented labels or recovered stochastic originals.

`custodian-key.json` publicly maps opaque template IDs to raw SHA256-bound JSON pointers and preserves all 159 typed telemetry outcomes. **For future real review, privately hold a new mapping and withhold it, reanalysis summaries, raw artifacts, benchmark trigger tests, and model assessments from first-phase reviewers until labels are locked.** Deterministic pseudonyms alone do not prove blinding; public corpus recognition and access to mappings remain risks. Review type is exposed, but cohort tags, model verdict/confidence, report status, PR/bug identities, and failure excerpts are absent from the reviewer template. Those omissions do not make this public template actually blinded.

For a future consented public evaluation:

1. A custodian recovers original candidate bytes from authorized retained artifacts, checks the archived SHA256, and records an acquisition receipt. If unavailable, retain the indeterminate case; do not regenerate and call it original.
2. Populate a **separate release packet with fresh privately mapped IDs**, not the frozen public template, with neutral before/after tree IDs, exact candidate bytes/hash, relevant supported API/contract/docs from frozen revisions, bounded effective prompts/context provenance in a separate privately held key, and complete execution/rerun receipts. Hash every released document; retain package hashes and access logs. Remove gold trigger tests, benchmark tags, model assessments/confidence, and report status from first-phase reviewer materials. Record material unavailable/missing explicitly.
3. Two independent human reviewers attest no involvement in generation/assessment and no access to labels/key. Each separately records assertion validity (`valid`, `invalid`, `indeterminate`), change intent (`intentional`, `unintentional`, `indeterminate`), report usefulness (`useful`, `not_useful`, `indeterminate`), rationale and evidence refs. Population cases get independently supported `clean`, `defective`, or `indeterminate` ground truth, including nonreports and risk skips; model silence is never ground truth.
4. Lock timestamped phase-one labels and packet hashes before unblinding. Retain both original labels, reviewer independence attestations, disagreements, and a third-reviewer adjudication with rationale. Never overwrite disagreement history.
5. Only then separately assess benchmark correspondence (`corresponds`, `does_not_correspond`, `indeterminate`) with designated defect/trigger material, retaining the phase-one labels. Publish semantic metrics only with adjudicated denominators and missing/indeterminate counts. Do not treat either this agent or a model as an independent human reviewer.

Future runner receipts must include executable/version, probe result/fallback reason, image manifest/config digests, actual run counts and rerun outcomes. A declared pytest arm must refuse fallback or retain it as a separate preregistered arm. Context must come from preregistered base/head trees, not future outer-checkout tests; archive effective bounded prompts and treat PR prose as untrusted. Suppressed-catch continuation must be a separate preregistered arm, never a replacement historical rate.

## Cost reconciliation contract

`cost-reconciliation-contract.json` is an empty future ledger contract, not reconstructed dispatch evidence. Received credits remain Click EUR0.08981148 / USD0.101980935540 (USD0.0025495233885 per 40 attempts), bugs EUR0.06703426 / USD0.076117402230 (USD0.0030446960892 per 25 attempts; USD0.00345988191954545 per 22 response-bearing rows), using both hashed ECB XML receipts at USD/EUR1.1355.

Click's 101 generation invocations minus four generation timeouts plus 16 assessor responses explains 113 received responses; **117 is not an instrumented HTTP dispatch/retry count**. Bug retries cannot be inferred from 78 responses. Malformed content can precede accounting; unobserved billed bodies and timeout charges are unknown, not zero. Row `cost_usd`/token/list-price estimates are not substituted for credit debits.

Future accounting must record every dispatch/retry and generator/assessor stage, retain transport/body/content/usage/billing status independently, and capture billing on receipt even when content parsing fails. Join a voluntarily owner-supplied sanitized statement by request IDs and allocation receipts. Opening balance + topups + refunds − all debits must equal closing balance, with other activity independently attributed. Unassigned lines, missing request IDs or unobserved charges prevent a reconciled total; a matching run window alone is insufficient. Keep provider and CI/runtime totals separate. No credentials are needed for this contract.

## Remaining gates

Actionably fixed here: scoped machine-readable metrics, explicit execution denominators/no-execution status, preservation of failures and raw hashes, blank blinded review population/candidate inventory, and precise future cost reconciliation rules. Remaining source instrumentation, temporal-context/prompt conflict fixes belong to their assigned source owners; exact candidate recovery and runner/dispatch receipts require authorized artifact retention or a future consented run. Independent human labels, representative cross-project sampling, wallet reconciliation, real usability/repeat-use/payment evidence and sustained operational SLOs remain open. This sidecar neither closes #73 nor certifies blanket engineering readiness.