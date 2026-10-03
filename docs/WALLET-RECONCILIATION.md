# Wallet reconciliation procedure (issue #73 cost gate)

Status: tool shipped, owner export outstanding. This document converts the
"#73 wallet/invoice reconciliation" item into a turnkey procedure. It does not
claim the reconciliation has been performed; the wallet export must come from
the owner because the provider exposes no billing API (verified below).

## Verified provider API surface (2026-10-04)

Nine candidate billing routes on `https://api.melious.ai/v1` were probed with
an authorized key: `credits`, `balance`, `usage`, `billing`, `subscription`,
`me`, `user/info`, `dashboard/billing`, `credits/balance`. All returned
HTTP 404. `GET /v1/models` without a token returns HTTP 401 as expected.
Conclusion: wallet/invoice data is available only from the provider web
dashboard; an agent cannot pull it. This narrows the #73 cost gate to exactly
one manual step.

## Procedure (owner, ~5 minutes)

1. Run any live evidence harness, which retains per-response provider billing
   rows, e.g. `scripts/ga73_live_stress.py --out out.json` (already run; see
   `docs/evidence/live-routing-20261004/`).
2. Print the wallet-export template:

   ```
   python3 scripts/reconcile_wallet.py --print-template > wallet.json
   ```

3. Fill `wallet.json` from the provider dashboard for a period covering the
   runs: opening/closing balance, any top-ups, and (if shown) the invoiced
   total. Amounts are decimal strings; never floats.
4. Reconcile:

   ```
   python3 scripts/reconcile_wallet.py --wallet wallet.json \
     --artifact docs/evidence/live-routing-20261004/live-routing-100x-run1.json \
     --artifact docs/evidence/live-routing-20261004/live-routing-100x-run2.json \
     --out wallet-reconciliation.json
   ```

Exit codes: 0 consistent; 1 local received debits exceed wallet-observed
spend (evidence and statement disagree; investigate, do not ship); 2 malformed
input. The report bounds failed/unreceived-call spend as
`implied_unaccounted_spend = wallet_observed_spend - received_credit_debits`
instead of assuming it is zero, and it never invents missing wallet fields.

## Scope and non-claims

- The reconciler covers provider debits only. CI compute minutes and other
  launch costs are outside the provider wallet and remain a separate line in
  the all-in USD-per-PR figure.
- A consistent report proves the owner-supplied totals cover the retained
  evidence; it does not prove the dashboard export itself is authentic.
- CI costs are observable to the owner in the GitHub Actions billing page;
  they are intentionally not estimated here.

## Live evidence this procedure reconciles

`docs/evidence/live-routing-20261004/` holds three runs on commit
`5ab5c31daab53864a6780e1de9bef13b68ae6b5e` (current `main` at capture time):
two 100-call bursts (99/100 ok each; the single failure in each was a
transient provider-side `InsufficientCreditsError` under a 100-worker burst,
with subsequent calls on the same model succeeding) and one 4/4 smoke probe
across `glm-5.3`, `glm-5.3-flash`, `kimi-k3`, `qwen3.8-27b`. Received
provider debits across all 204 calls sum to EUR 0.06817020 by exact Decimal
arithmetic over the retained per-response billing rows. The two transient
billing refusals are retained as failure rows; their spend is unobserved and
is exactly what the reconciliation step bounds.
