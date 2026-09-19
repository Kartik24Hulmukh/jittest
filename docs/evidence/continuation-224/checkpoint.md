# Continuation checkpoint — NO-GO

Latest combined local source: d19bda8 plus documentation-only 2e7a172. Full pytest: 1230 passed, 1 skipped, 202 subtests passed, 183.06s. Focused env/process/swarm: 25 passed in 25.73s. Native fixture: all 10 tests passed in 46.23s; clean stdlib-only virtualenv native test passed in 7.114s. Ruff clean.

This session pushed 588007b, 305a801, e0618ca for authentic offline wheel provisioning in CI. Another contributor concurrently pushed d19bda8 and 2e7a172; integrated by fast-forward, never force-pushed. CI/workflow fix cycles: 3 (<5). No unvalidated process architecture rewrite attempted.

Frozen stress gates FAIL: 100 real parent-exit process journeys leave 200 owned readers alive; harness cleanup reclaims them. Captured output grows to all 16 MiB supplied. See issue #225 and executable adversarial_repro.py. 100 simultaneous real timeout journeys under competing suite load have 8 cleanup durations >=200ms; P50/P95/P99/max 96.670/285.860/295.056/299.640ms, zero unhandled exceptions or surviving readers in that particular scenario. See issue #223 for exact reproducer. These measurements exclude startup latency and do not relax thresholds.

Probe metrics are not engine throughput: post-swarm.json is 120 personas/100 workers/1000 probe requests; passed, 1089.7 rps, P50/P95/P99 73.666/120.839/141.330ms, recovery 1.650ms, RSS sampled 29.1/52.4 MiB. Two RSS points do not certify absence of leaks.

Do not merge at less than 100% of the frozen gates. PR #224 remains a continuation, not production certification. Auto-merge disabled; #223 must not auto-close while reproduced SLO violation persists. Existing launch_gate.json says GO_LAUNCH_NOT_GA and does not include these newly reproduced engine failures; the correct comprehensive launch decision is NO-GO. Issue #73 retains unresolved real-world catch-rate/FPR/cost/customer-evidence requirements.

No credentials included in this checkpoint. Rotate the PAT exposed in the user-supplied report and conversation.
