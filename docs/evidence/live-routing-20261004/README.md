# Live Melious routing evidence — 2026-10-04

Commit under test: `5ab5c31daab53864a6780e1de9bef13b68ae6b5e` (`main` head at
capture). Harness: `scripts/ga73_live_stress.py`, 256-token cap, truncation
escalation disabled, deadline 30 s, max 4 in-flight per model, all failure
rows retained. No customer-source code was sent; prompts are synthetic
echo-checks.

| Artifact | Calls | Result | P50 / P95 / P99 (s) | Throughput |
|---|---|---|---|---|
| live-routing-100x-run1.json | 100 (25/model) | 99 ok, 1 failed | 3.368 / 12.939 / 15.146 | 6.40 calls/s |
| live-routing-100x-run2.json | 100 (25/model) | 99 ok, 1 failed | 4.233 / 17.056 / 18.688 | 5.17 calls/s |
| live-routing-4x-probe.json | 4 (1/model) | 4 ok | 0.606 / 1.611 / 1.611 | 2.01 calls/s |

Failures: run1 index 44 (`glm-5.3`) and run2 index 75 (`qwen3.8-27b`), both
`InsufficientCreditsError` ("billing refusal: account credits/quota
exhausted") while later calls on the same models succeeded; the 4/4 probe ran
clean immediately after run1. Interpretation: transient provider-side billing
refusal under a 100-worker burst, not a routing defect and not an exhausted
wallet. The router typed it correctly and the harness failed closed, as
designed. This is evidence for the #73 wallet-reconciliation item: failed
calls may carry unobserved spend, which `scripts/reconcile_wallet.py` bounds
once the owner supplies a dashboard export (the provider exposes no billing
API; see docs/WALLET-RECONCILIATION.md).

Scope limits: finite bursts on synthetic prompts; not a sustained SLO, not a
catch-rate or FPR measurement, not a USD-per-PR figure. Threads before/after
1/1 in every run; no retained Python threads after router close.
