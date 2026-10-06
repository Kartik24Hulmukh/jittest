# Owner launch packet — October 2026 (every remaining action, turnkey)

Status on 2026-10-04, main @ 05138a0: all 24 protected CI checks green, zero open
issues or PRs, issue #73 closed by the owner at the PR #246 merge commit. Full
suite: 1641 passed / 9 skipped / 527 subtests; ruff and mypy clean. Round-7
offline stress and chaos evidence is committed under
`docs/evidence/live-routing-20261004-round7/`.

Engineering can take the launch no further from inside the code. The actions
below are the complete remaining set; each is owner-only and each now has a
turnkey tool or a written procedure. Total owner effort: roughly one hour plus
correspondence time.

## A. Provider account (10 minutes)

1. **Rotate the Melious API key.** It was transmitted in plaintext chat and must
   be treated as compromised. Generate a fresh key in the Melious dashboard and
   update the CI secret `MELIOUS_API_KEY` (repo Settings > Secrets and variables
   > Actions). Delete the old key.
2. **Top up the wallet.** As of 2026-10-04 the wallet is exhausted: every live
   completion call across all four models returns `InsufficientCreditsError`
   (evidence: `docs/evidence/live-routing-20261004-round7/`). Until topped up,
   no live routing or evaluation run can succeed anywhere — including CI.
3. **Export the wallet statement** for the evaluation period from the Melious
   dashboard (the API exposes no billing endpoint; nine candidate routes probed
   2026-10-04, all HTTP 404 — this is a verified API-surface fact, not a guess).

## B. Close the #73 cost gate (5 minutes after A)

```bash
python3 scripts/reconcile_wallet.py --print-template > wallet.json   # fill from dashboard export
python3 scripts/reconcile_wallet.py --wallet wallet.json \
  --artifact docs/evidence/live-routing-20261004/live-routing-100x-run1.json \
  --artifact docs/evidence/live-routing-20261004/live-routing-100x-run2.json \
  --artifact docs/evidence/live-routing-20261004/live-routing-4x-probe.json \
  --artifact <all other eval evidence artifacts with rows>
```

Exit 0 = reconciled (the delta between wallet-observed spend and retained
received debits is the upper bound covering failed calls; never assumed zero).
Exit 1 = inconsistency, investigate before launch. Procedure and scope:
`docs/WALLET-RECONCILIATION.md`.

## C. Rerun the bounded live-routing proof (5 minutes after A.2)

```bash
MELIOUS_API_KEY=<new key> python3 scripts/ga73_live_stress.py --calls 100 --workers 100 --out live.json
```

Compare against the round-6 green baseline (99/100 ok, P99 15-19 s at 100
workers). Do not proceed to E with a red routing run.

## D. Quality gates that need humans (the honest core of #73)

These are the gates no agent can clear without fabricating evidence, and the
project's own acceptance spec correctly forbids fabrication:

1. **Independent blinded labels.** The measured numbers (64% mechanical catch
   on 25 BugsInPy specimens; 0/40 surfaced reports with ~7.5% upper bound on
   settled Click PRs) are screening proxies, not validated recall/FPR. Needed:
   an independent labeler, blinded to jittest's verdicts, adjudicates the 16
   suppressed catching candidates and a sample of the apparently-clean
   population. `eval/ga73_acceptance.py` already contains the workflow; the
   label CSV schema is defined there.
2. **Representative multi-project cohort.** Current evidence is BugsInPy (3
   projects, historical) + Click (1 project). A GA claim needs the default
   product cohort (`eval/default_product_cohort.json`, `docs/DEFAULT-PRODUCT-COHORT.md`)
   executed on a funded wallet against the published thresholds (recall > 25%,
   FPR < 10%, all-in cost < $1/PR) enforced fail-closed by PR #243.
3. **Sustained SLO.** Point-in-time stress passes (100 personas, P99 57.5 ms;
   1,000-request chaos, P99 144.9 ms — round-7 re-verified green offline) are
   not a sustained availability SLO. Run the eval workflow's sustained mode on
   a funded account for the declared window.

## E. Founder-only gates (G0-1, G0-2)

- **G0-1 stopwatch experiment** (~1 hour): clone BugsInPy, take 5 bugs, and
  hand-write a test per bug that passes on fixed and fails on buggy. Decision
  rule is pre-registered: average >= 40 min per bug means the product earns its
  place; <= 10 min means stop. Record bug id, minutes, y/n, and what was hard.
- **G0-2 maintainer yeses**: ask 10-20 maintainers of active Python repos the
  one question; GA requires two written yeses with repo names.
- **PyPI 0.4.0 yank** (see `YANK-REASONS.md`): the published 0.4.0 wheel
  reports `__version__ == "0.3.5"`. A maintainer must yank 0.4.0 on PyPI; only
  the package owner can do this. Never reuse the v0.4.0 tag.
- **SLSA / trusted publishing** (release.yml) still requires founder approval
  to modify; see `docs/RELEASE-APPROVAL.md`.

## F. What "Go" means when the above is done

With A-E green, the honest launch statement is: GA thresholds measured on a
representative cohort with independent labels, wallet-reconciled cost, and a
sustained SLO — at which point the status moves from `GO_LAUNCH_NOT_GA` to Go.
If any gate fails, publish the failure exactly as measured; the project's
acceptance machinery (PR #243) will refuse to self-promote regardless.
