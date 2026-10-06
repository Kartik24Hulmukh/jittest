# Round 7 evidence (2026-10-04, main @ 05138a0)

Two result classes, recorded honestly:

## 1. Offline stress + chaos (green, recorded)

| Harness | Result |
|---|---|
| `persona_swarm_100x.py` (100 personas, 1,000-request burst, 100 workers) | passed=true, 0 panics/unexpected outcomes, P50/P95/P99 92.7/98.9/102.4 ms, recovery 1.08 ms (< 200 ms SLO), 1054 req/s, RSS 29.3-52.7 MiB, tracemalloc peak 8.69 MiB |
| `chaos_100x_probe.py` (100 clients x 10 scenarios, 1,000 requests) | 0 tracebacks, 0 transport errors, 0 secret/traceback log leaks; P50/P95/P99 32.7/215.6/228.8 ms; recovery 35.3 ms (< 200 ms SLO); server alive after chaos |

Raw artifacts: `persona-swarm-20261004-round7.json`, `chaos-100x-20261004-round7.json`.

## 2. Live Melious routing (provider wallet exhausted; fail-closed evidence)

Both the 100-call burst and the 4x probe returned **0 successful completions**:
every completion call across all four catalogue models failed with the provider
error class `InsufficientCreditsError` (HTTP failure typed by the router,
retained as failure rows; no success-only filtering). A direct unauthenticated
`/v1/models` check still returns 401 and an authenticated one returns 200, so
the API surface and key validity are intact — the wallet balance is exhausted.

What this run demonstrates positively:

- The router types provider billing refusals correctly and the harness fails
  closed with failure rows retained (no fabricated successes, no retry storm:
  53.5 calls/s bounded dispatch, threads 1->1).
- `reconcile_wallet.py` fails closed on these artifacts (exit 1: zero rows
  carry debits and the wallet cannot be observed — the cost gate cannot pass).
- Per-row `provider_billing.provider_credit_debit_eur` is null for every failed
  call; the nulls are never zero-filled, per the no-overclaiming invariant.
  Each artifact carries `wallet_state_during_run` and
  `credit_debit_fields_policy` stating this explicitly.

What is NOT demonstrated (and must not be claimed): successful live routing on
05138a0. The last green live evidence is the 2026-10-04 round-6 bursts under
`../live-routing-20261004/` (99/100 ok x2 + 4/4 probe on 5ab5c31, the parent of
the current head).

**Owner action required:** top up the Melious wallet (or supply a funded key).
After top-up, rerun:
`MELIOUS_API_KEY=... python3 scripts/ga73_live_stress.py --calls 100 --workers 100 --out <new artifact>.json`
and `scripts/reconcile_wallet.py` with the dashboard export
(`--print-template` emits the template). Both steps are turnkey.
