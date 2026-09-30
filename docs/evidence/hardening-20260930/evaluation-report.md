# Evaluation handoff — GA73 reanalysis, 2026-09-30

## Outcome and ownership

Prepared an additive, deterministic offline reanalysis at `/data/jittest` on baseline `bf642162a3059b3ec116c2d0db9333892fa6c9f7`, branch `harden/jittest-v1-launch`. **#73 is not validated GA recall/FPR/total-cost evidence and must not be closed as GA.**

Owned edits only:

- `eval/RESULTS.md` — removed blanket engineering-readiness wording, separated response coverage from paired execution, and made missing suppressed-candidate/runner evidence explicit.
- `eval/ga73_reanalysis.py` — standalone stdlib JSON/XML analysis; imports no production/corpus code and makes no network calls.
- `docs/evidence/ga73-reanalysis-20260930/{baseline-sha256.json,reanalysis.json,reviewer-template.json,custodian-key.json,cost-reconciliation-contract.json,README.md}`
- `tests/test_eval_ga73_reanalysis.py` — 10 trusted evaluation-only tests.

Other working-tree changes seen during final status belong to concurrent owners; I did not edit or revert them. No corpus code execution, credentials, paid calls, GitHub mutation, commit, or push occurred.

Read the **full** `/data/research/council-evaluation.md`, relevant Astra review §§6, 11, 18 and fastest validation tests, strategy-final §§6, 17–18, current evaluation summary/gates, and retained raw cohort/manifest/FX artifacts.

## Baseline frozen before edits

`baseline-sha256.json` records 154 original evaluation/evidence file hashes before task-specific implementation or RESULTS edits. All **60 original evidence files** under `docs/evidence/ga73-20260930` were verified unchanged after work; original `RESULTS.md` pre-edit SHA is retained. Original raw/mechanical fields, failures and rates were not rewritten. New analysis also records its own source SHA256.

Primary input hashes:

| Input | SHA256 |
|---|---|
| `ci-pr-qualified/ga73-pr-pilot.json` | `9028a73dafb95d5f35f1fe2e53baf1bd8fe549bcd440f66c774847b52c2616c4` |
| `ci-default-bugs/ga73-default-bugs.json` | `6f53e740e7783c639ac53cdd5df10248df4e38401790128cc625bd4fa6a36969` |
| Both cohort ECB FX XML receipts | `f95b3803d0f531bfc205f101974090d7454e29b8e4d1ea9db179ef09a64ad931` |

## Measured observations, not semantic labels

| Measure | Historical bugs | Conditional Click PR screening |
|---|---:|---:|
| All attempted selected rows | 25 | 40 |
| Response-bearing rows | 22/25 | 40/40 |
| Received responses | 78 | 113 |
| Mechanically caught rows | 16/25 (64%) | 11/40 |
| Mechanically catching candidates | 20 | 16 |
| Rows with surfaced reports | 12/25 (48%) | 0/40 |
| Candidate reports | 13 | 0 |
| Paired execution rows | 20/25 | 12/40 |
| Typed candidate outcomes retained | 58 | 101 |
| Oracle-entry candidates with any recorded outcome | 38 | 24 |
| Head-uncollectable / oracle-entry candidates | 0/38 | 1/24 |
| Paired candidate outcomes | 34 | 23 |
| Unpaired/partial candidate outcomes | 4 | 1 |
| Received-response credit debit EUR | 0.06703426 | 0.08981148 |
| Received-response credit debit USD, FX1.1355 | 0.076117402230 | 0.101980935540 |
| USD / all attempted selected rows | 0.0030446960892 | 0.0025495233885 |
| USD / response-bearing rows | 0.003459881919545454545454545455 | 0.0025495233885 |

Bugs' conditional mechanical diagnostic remains 16/22; the old rounded 0.727 is preserved in raw and the sidecar derives the exact denominator-based value. Project mix remains PySnooper3 / tqdm9 / youtube-dl13; three default-risk skips remain in all-attempted rates.

Click retains 55 Python-changing PR population cases, 40 eligible attempts and 15 static exclusions (40/55 eligibility); 20 no-call proofs remain zero. The unrelated legacy `screened_out=55` field is explicitly not added to/relabelled as this frame. Click dispositions remain 64 declines, 16 catches, seven safety rejections, seven both-fail latent cases, four timeouts, two parse failures, one uncollectable. Bugs retain 20 catches, 14 both-fail latent, 12 safety rejections, eight declines, four head-pass outcomes.

Click model assessments suppressed all 16 catches (15 intended/one unclear); bug catching-candidate model assessments remain 13 real-regression/four unclear/three intended. These are **model assessments, never independent human labels**. Fourteen Click catch excerpts mention `_minirunner`; the other two do not identify their runner. Sidecar only checks archived manifest/row applied-head identities; it does not claim a new Git-parent audit.

The retained zero-report bounds remain 7.5% rule-of-three and 7.21575245055146% exact one-sided, conditional on independent common-rate sampling assumptions not established by this historical single-project frame. Neither is labeled FPR. Reconciled provider total, CI/runtime cost, adjudicated recall/FPR and precision are null.

Machine fields match requested scopes exactly:

```text
qualification_scope = limited_response_and_collection_screening
independent_labels = absent
runner_identity = not_explicitly_archived
suppressed_candidate_review_material = incomplete
cost_scope = received_response_credit_debits_only
```

## Narrow gaps addressed now

1. Added explicit response, oracle-entry, paired, partial and population denominators. No execution is `not_assessed`; refusals cannot dilute oracle-entry collection failure. Regression fixture retains the old pooled 10/60 pass while demonstrating 10/11 oracle-entry failure. No production gate or historical run is retroactively changed.
2. Added a **PUBLIC TEMPLATE, NOT ACTUALLY BLINDED** review inventory: 116 opaque cases = 80 whole-population cases (55 PRs +25 bugs) +36 catching-candidate cases. All labels/reviewer IDs remain null. All 159 typed outcomes remain in the public reference mapping with SHA-bound source pointers. The reviewer template omits cohort/model/report fields, but the publicly committed mapping permits unblinding; omission is not an effective-blinding claim. Future real review requires fresh IDs and a separately privately held mapping. The README requires original byte recovery/hash verification, two independent human reviewers, locked phase-one judgments, retained disagreements, and separately unblinded benchmark correspondence.
3. Added an empty future cost reconciliation contract, including generator/assessor dispatch/retry IDs, body/content/usage/billing status, unknown-not-zero debits, sanitized owner statement joins/allocation receipts and separate provider/CI totals. No invented ledger events or reconciled expenses. 101 generation invocations −4 timeouts +16 assessor responses explains Click113, but neither101 nor117 is an instrumented HTTP dispatch total.
4. Corrected blanket engineering language while retaining archived CI observations at their recorded revisions.

The public template cannot yet support blinded adjudication: exact candidate bytes, supported contract/context and per-execution provenance are missing, and its mapping is public. It deliberately marks every case `template_only_unadjudicatable_from_retained_archive`. Future private custody must not reuse these publicly mapped IDs or distribute its private mapping to reviewers before labels lock.

## Checks and exact commands

Executed from `/data/jittest` after final generation:

```bash
/data/venv/bin/ruff check eval/ga73_reanalysis.py tests/test_eval_ga73_reanalysis.py
python3 eval/ga73_reanalysis.py
python3 eval/ga73_reanalysis.py --check
/data/venv/bin/python -m pytest tests/test_eval_ga73_reanalysis.py
```

Results: **Ruff passed; deterministic write/check passed; 10 tests passed in 0.20s.** Earlier lint found four issues (import order, strict zip, nested if); corrected only my files and reran successfully. No full-suite claim is made here.

Tests cover frozen counts/scopes, full-precision USD and denominators, dilution counterexample, no-execution not-assessed, inconsistent uncollectable rejection, packet completeness/blinding/no fabricated labels, raw hash integrity, malformed/noncredit billing rejection, deterministic checked-in output and empty unreconciled cost contract.

Independent numeric checks: Decimal credits versus scaled integers, mechanical telemetry counts versus bug row status/catching counts, recorded FX values versus XML, unique applied pair and population frame partition, and all no-call counter checks.

Profiler outputs are outside the checkout at `/data/analysis/ga73-{click,bugs}-profile.txt`; immutable copies at `/data/raw/ga73`. No duplicate Click rows found; bug identifiers remain strings keyed by project, not standalone numeric IDs. Constant outcome/runner/contract fields are expected archive properties, not reasons to drop observations. Null billing belongs to three preserved no-response risk skips. Row `cost_usd` profiles are estimates and were not substituted for credit sums.

## Still open / source-owner handoff

- Recover exact original candidate material where available; otherwise retain historical indeterminacy. Opt-in future evaluation retention must cover suppressed catches, full execution/rerun receipts, effective prompts and context hashes without weakening production privacy.
- Record actual runner executable/version and probe/fallback reason per execution; refuse fallback in a declared pytest arm or preregister a separate runner arm.
- Record every generator and assessor dispatch/retry; capture billing before content parsing; reconcile owner-supplied sanitized wallet/invoice lines. Cannot infer missing past dispatches/debits.
- Fix outer-checkout future-test metadata and contradictory assessor instructions in source-owner scope. Use revision-bound context, PR prose as untrusted data, and no benchmark gold labels in generation.
- Independent human semantic/population labels, representative cross-project/time sampling, separate suppressed-catch continuation study, usability/repeat-use/payment trials, and sustained SLOs remain future gates.

No further historical computation can manufacture those missing artifacts or human labels. This work advances evaluation auditability narrowly without closing GA.