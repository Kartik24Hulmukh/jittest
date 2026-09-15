# jittest — Launch Go/No-Go Gate (window: 2026-09-16 / 2026-09-17)

**Decision at `main` after PR #205 (`f3c3746`): `GO_LAUNCH_NOT_GA` — ship the launch, do not announce GA.**
Report: `docs/evidence/launch-gate-20260916.json` (digest `244e0ac71e23ed64…` (7 gates, incl. `workflow_cli_contract`)). Reproduce:

```bash
PYTHONPATH=src python scripts/launch_gate.py --json /tmp/gate.json   # add --full for the 1200+ test suite
```

## Why one gate
Six hardening cycles produced six closeout documents, each hand-summarising "tests green, ga_ready false".
A launch decision that lives in prose drifts. `scripts/launch_gate.py` makes the decision *computed*:
one command, one JSON, one digest, exit code 0/1. `ga_ready` is **derived** from the open-blocker list
(#73, #198, #199) and cannot be flipped without deleting those rows in a reviewed PR.

| Gate | What it proves | Result 2026-09-15 |
|---|---|---|
| `ruff` | src/tests/scripts/eval lint-clean | ok |
| `version_drift` | 0.4.1 agrees in 4 places | ok |
| `release_mapping` | tag → source SHA → wheel/sdist SHA-256 (11 checks) | ok |
| `receipts_recompute` | every published receipt re-verified offline by the shipped CLI | ok (see finding) |
| `soak_evidence` | committed 100k-op soak still satisfies its own leak contract (slope ≤ 1 KiB/1k ops, 0 errors, 1 digest) | ok |
| `tests` | focused launch suites (soak, stress, chaos, observability, phase boundaries, receipts, CLI) | ok |

## Real defect found by the gate (day one)
`docs/evidence/quadrants/non_discriminating_evidence.json` — a *showcase* receipt linked from the
README — is **refused by `jittest verify-receipt`** (exit 5, `semantic_invalid`). Its signature is intact,
but the legacy 2.0 payload records `base_execution.outcome = NOTRUN` while claiming `non_discriminating`,
which by definition requires PASS on both revisions. Two honest options existed:

1. Regenerate it (needs the pinned Flask checkout `12e95c93..d3b78fd1` and a real run — owner action).
2. Hide it or loosen the checker — **rejected**; that would be the eighth fabrication in the ledger.

Shipped: the gate pins this receipt as `KNOWN_REFUSED_RECEIPTS` and asserts it *stays refused* with an
intact signature. The tool's fail-closed behaviour on its own stale evidence is now a regression test.
Regeneration via `scripts/generate_quadrants.py` remains a tracked follow-up (see the issue opened with this PR).

## Council premortem (5 parallel lenses, 2026-09-15)
| Lens | Failure mode | Mitigation in this PR |
|---|---|---|
| SF Founder | "All green" in six PDFs, nobody can say *which* commit is launchable | Single computed decision + digest per commit |
| Red Team | Evidence directory contains receipts the product itself rejects | Recompute gate over every published receipt; found one |
| Research Scientist | Soak JSON edited by hand drifts from the contract it claims | `check_soak_evidence` re-validates the committed JSON on every run |
| Systems Architect | Gate itself is flaky / non-deterministic | Volatile fields (elapsed, python) excluded from digest; pure functions unit-tested |
| Release Engineer | GA flag hand-toggled under launch pressure | `ga_ready = not GA_BLOCKERS`; tests pin the derivation |

## Launch-day runbook (Sept 16–17)
1. `git fetch && git checkout origin/main && PYTHONPATH=src python scripts/launch_gate.py --full --json gate.json`
2. Require `decision != NO_GO`. Publish the digest with the announcement.
3. Announce **launch of the verified 0.4.1 artifact + open development main**; do **not** say GA, do not tag, do not publish to PyPI.
4. Rotate the GitHub PAT that was pasted into automation prompts (still exposed as of 2026-09-15).
5. Post-launch: close #199 by cutting 0.5.0 through the protected release workflow once #198 items 1–2 land.

## Not claimed
Container-daemon chaos (no Docker/Podman on the hardening host), multi-hour soak, Option C public-path wiring,
trusted runtime inventory, real catch-rate/FPR/USD-per-PR evaluation. `ga_ready: false`.


## Addendum 2026-09-15 (evening): workflow ↔ CLI contract gate

The Gate-1 smoke dispatch for #73 died in 0 s at argparse (PR #208 found two wiring
bugs in `eval.yml`). Council premortem: *any* workflow that shells out to a repo script
can drift from that script's flags, and CI only ever ran the scripts it never dispatched.

Shipped `scripts/check_workflow_cli_contract.py` (stdlib only, runs in the no-dependency
CI cell): every `python eval/*.py|scripts/*.py` line in every workflow is checked against
the script's `argparse` contract read via `ast` — required flags must be literal (not
conditionally appended), unknown flags fail, and `--out` must match what later steps of
the same job upload/assert. 16 invocations across 7 workflows are covered; it is the 7th
gate in `launch_gate.py`.

On the unfixed tree it reports exactly three defects for `eval/run_bugsinpy.py`: the two
from #208 plus a third #208 missed — the workflow passed `--projects <comma-list>` while the
script only defines a repeatable `--project`, so every *filtered* dispatch would still have
died. The workflow now splits the input into repeated `--project` flags.

Also observed (not fixed here): running the test suite rewrites the tracked file
`jittest-evidence/evidence-test_bar-cb526fade08e.json` (test pollution of committed
evidence) — tracked separately.
