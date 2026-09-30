# Qualified limited-cohort evaluation — 2026-09-30

**Decision: retain limited mechanical, response-coverage and collection-screening observations; GA remains unproven.** Archived CI checks below passed at their recorded revisions; they do not establish that all engineering or evaluation gates pass. These are isolated execution and received-response credit-debit observations, not independent human labels, validated recall/FPR, total charged spend, adoption evidence, or a sustained service guarantee. Additive reanalysis, raw SHA256 verification, explicit denominators and unfilled adjudication/cost contracts are under `docs/evidence/ga73-reanalysis-20260930` (`python3 eval/ga73_reanalysis.py --check`).

## Product operating point

Melious `glm-5.3-flash`, risk threshold 0.35, max five targets and four candidates per target. Historical bug measurements use an offline Python 3.8 compatibility runtime; modern Click PR measurements use pinned Python 3.13. Jittest's host remains supported Python. Request/response guards are bounded but do not reserve wallet funds.

## The three measurements

- **Catch:** 16/25 frozen BugsInPy specimens had a mechanically catching candidate (64% of all attempted); 12/25 surfaced reports (48%). Twenty-two called the model; three risk skips remain in the denominator. This is three-project historical coverage, not universal recall.
- **PR noise screening:** zero reports on 40/40 response-bearing default-risk-eligible applied Click PRs; only 12/40 have recorded paired execution. Report the approximate 95% upper bound **7.5%** alongside the zero-observed rate. This is a conditional apparently-uneventful-merge screening proxy, **not independently labeled FPR**. The exact zero-success one-sided binomial bound is about 7.22%; the retained workflow uses conservative rule-of-three 7.5%. Both bounds assume independent/common-rate sampling, not demonstrated by this single-project historical cohort.
- **Observed successful-response billing:** EUR0.08981148, USD0.101980935540 total, or **USD0.0025495233885 per evaluated PR**, using ECB USD/EUR1.1355. All forty rows contain complete credits-paid response metadata (113 received responses). This excludes failed/unreceived-response spend, CI/container costs, and wallet/invoice reconciliation. Token/list-price estimates are separate, not substituted for these debits.

## Sampling and honest failures

The predeclared Click sample contains forty eligible actual applied merge commits from fifty-five Python-changing PRs: fifteen static below-risk/no-target exclusions are preserved. This is 72.7% rank eligibility in that sampling frame, not 100% general-traffic coverage. Five-year lookback, ninety-day settling, first-parent binary merges, captured authoritative GitHub PR identities/title/body. No outcome-dependent filtering. PR bodies were captured before measurement and may differ from merge-time versions.

Twenty real-pipeline no-call proofs passed: five formerly noisy docs-only PRs and fifteen static exclusions, each with zero generation attempts, received responses and reports. Docs-only results explicitly report no Python changes. The prior stale-branch pilot is INVALID for FPR and remains preserved under ci-pr-invalid. The first youtube-dl pilot failed its sample floor and remains retained.

Corrected PR candidate dispositions include 64 model declines, 16 mechanical catching candidates, seven safety refusals, seven both-fail latent cases, four timeouts, two parse failures, and one uncollectable candidate. Those are typed bounded outcomes, not hidden successes. The model suppressed all 16 catches (15 `intended_change`, one `unclear`); intent is not independently established. No surfaced claim exists to estimate surfaced-claim precision in this sample; suppressed assertions and the entire apparently-clean population still need independent review. Exact suppressed-candidate test bodies are not retained, so the historical archive is insufficient for that adjudication. Runner identity is not explicitly archived per execution; 14/16 catching excerpts mention `_minirunner`, and the other two are unidentified.

## Reproduction and provenance

- Corrected PR run: https://github.com/Kartik24Hulmukh/jittest/actions/runs/36638597532 — code commit5331774; immutable raw JSON, image pins and FX retained under docs/evidence/ga73-20260930/ci-pr-qualified.
- Matching bug run: https://github.com/Kartik24Hulmukh/jittest/actions/runs/36635109632 — raw JSON under ci-default-bugs.
- Fresh real-daemon proof: https://github.com/Kartik24Hulmukh/jittest/actions/runs/36640058668 — dependency execution, descendant cleanup, public phase enforcement, receipt-signature/tamper checks and live registry pinning passed.
- Independent Decimal and scaled-integer sums, unique pair/PR checks and all no-call identities passed; ga73-final-audit.json carries full precision and raw SHA256s. Generic profiling required extracting the forty-row array from the nested artifact; constant outcome/contract fields are expected, not dropped observations.

Complete source suite: 1,322 passed, nine explicitly skipped, 210 subtests passed under eight-worker contention. All nine Ubuntu/macOS/Windows x Python3.11–3.13 matrix jobs passed. Exact CI Ruff, full mypy (53 source files), and 25-invocation workflow contract passed. Actual test-running launch gate returns GO_LAUNCH_NOT_GA, not GA-ready; skipped tests are not described as executed.

## Remaining GA gates

Independent blinded clean/bug ground-truth and multi-project representative product-rate validation; exact candidate retention, runner/request provenance and temporal-context controls; provider wallet/invoice reconciliation including failed responses; sustained availability and cancellation/load SLOs; externally observed pilot/adoption/payment evidence. These include fixable instrumentation and methodology gaps, not merely owner authentication blockers. They cannot honestly be eliminated by renaming a screening proxy as FPR or declaring traction without users.
