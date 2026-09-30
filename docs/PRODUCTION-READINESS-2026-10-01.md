# October readiness: bounded preview, not GA

This continuation starts from `e6c912d12c127a8aab40d7dc867f77483567899e`.
Issue #73 is the only open GitHub issue observed. The attached historical patch
paths are not present on this fresh computer; their existence is not evidence
that they were integrated. Current source and hosted settings were inspected.

## Current-state audit

| Area | State | Evidence / remaining requirement |
|---|---|---|
| CLI, signed paired execution, GitHub Action | Done within supported scope | Existing real execution tests; new attempt-census qualification must run on the final PR head |
| Default verifier attempt denominators | Previously missing; repaired in this PR | Exact candidate hashes/pins, execution records, terminal dispositions, Action snapshot/journal, installed-wheel and consumer checks |
| GA promotion control | Previously broken; repaired in this PR | Static blocker deletion cannot substitute for validated evidence; invalid evidence fails closed |
| Exact-byte publication approval | Previously missing; repaired in this PR | External raw-manifest digest, source/artifact/run/build-attempt/effect bindings and downstream rechecks |
| Hosted publication protection | Missing | Owner-authenticated inspection: `pypi` had no protection rules, no deployment-ref policy and no approval variable |
| Four requested Melious routes | Done for a bounded burst, not sustained SLO | New 4/4 smoke and 100/100 completion burst on baseline source; 25 calls per model |
| Legacy smoke/pilot collection screening | Repaired in this PR | Shared oracle-entry denominator; generation refusals cannot dilute collection failures; malformed/no-entry cases refuse |
| Independent semantic catch/FPR evidence | Missing | Original independent labels and complete original candidate material remain unavailable |
| Reconciled all-in USD per PR | Missing | Received-response debits are not wallet/invoice plus failed/unreceived calls plus CI reconciliation |
| Customer value, adoption, payment, traction | Missing independent evidence | Agents cannot perform the founder's human stopwatch experiment or fabricate maintainer consent |
| Production-wide / 100x guarantee | Not established | Finite probes, fixtures and CI are not representative sustained deployment evidence |

## Frozen baseline and new live measurements

The exact baseline full suite passed: 1,491 normal case elements, 321 additional
subtests, 12 explicit skips, zero failures/errors, 210.012 seconds. Test XML suite
`tests` includes subtests; it must not be described as 1,824 normal test cases.
The initial overlapping mutable-checkout test process was stopped; only the
separate pinned worktree's full result is the frozen baseline.

The new Melious burst used 100 workers, 100 completions, 256 output-token cap,
15-second deadline, truncation escalation disabled, all failure rows retained.
Models: `glm-5.3`, `glm-5.3-flash`, `kimi-k3`, `qwen3.8-27b`.

| Measurement | Result | Scope |
|---|---:|---|
| Routing completed | 100/100 | 25 per requested model route |
| Routing P50 / P95 / P99 | 4.122 / 8.014 / 8.773 seconds | Nearest-rank finite-burst quantiles, not a sustained SLO |
| Routing throughput | 9.575 completions/second | Entire measured burst duration |
| Routing sampled RSS start/end | 20,924 / 39,100 KiB | Not a continuously measured memory ceiling |
| Routing Python threads before/after | 1 / 1 | No retained Python thread observed after router close |
| Received credit debits, smoke + burst | EUR 0.0340989 | 104 completion rows only; not reconciled total spend or USD per PR |
| Probe-plane personas | 120 synthetic personas / 20 behaviors | Not 120 humans, customers, or representative product users |
| Probe-plane burst | 1,000 requests / 100 workers | Baseline probe HTTP plane only |
| Probe P50 / P95 / P99 | 106.751 / 136.528 / 142.784 ms | Finite burst |
| Probe throughput | 876.6 requests/second | Finite burst |
| Probe recovery | 1.006 ms | Single post-burst health probe |
| Probe sampled RSS floor/ceiling | 25.9 / 38.9 MiB | Synthetic probe workload |
| Contended timeout recovery worst | 36.184 ms | 100 timed-out runs, 20 workers, 8 CPU burners |

Probe baseline recorded no unhandled panics or unexpected dispositions and the
server thread stopped. Timeout recovery recorded no errors or leaked Python
threads. These observations do not prove zero leaks under all workloads.
Two completion rows in the live burst had two routing attempts; unknown charges
from failures/unreceived responses are not assumed to be zero. The billing
summary sums received provider credit-debit strings with exact Decimal arithmetic.
No customer-source code was sent in these synthetic routing prompts.

## Five-risk premortem and concrete response

1. **JIT races / overlapping attempts:** bind candidate bytes and revision pins
   to run records and preserve terminal outcomes, rather than infer the attempted
   population from successful receipts. Real run concurrency remains measurable,
   not certified by an in-memory concurrency fixture.
2. **Thread starvation / cancellation:** retain bounded subprocess lifecycle and
   actual timeout stress results. Probe and timeout harnesses are different
   workloads; neither certifies sustained hosted availability.
3. **Nondeterministic / missing-material drift:** freeze 78 original GA evidence
   file hashes and deterministic reanalysis; do not regenerate lost candidate
   bodies or alter historical labels. New census capture cannot retroactively
   fill an old evidence gap.
4. **False GA / misleading economics:** require evidence acceptance beyond an
   empty static blocker list. Peer review reproduced a per-target cost
   reallocation bypass in synthetic acceptance fixtures; regression coverage
   must reject it. Attestations are checked documents, not independently verified
   human identity or proof of actual blinding.
5. **Unauthorized / mismatched publication:** require effective external
   approval of exact raw manifest, source/context, artifact bytes and each effect.
   Source-local checks cannot prove variable origin or prevent a malicious tag
   from replacing the workflow; external reviewer/ref/workflow policies remain
   mandatory. No release, tag advancement or PyPI upload is authorized by green
   tests alone.

## Evidence acceptance, not fabricated completion

See `GA73-ACCEPTANCE.md`, `RELEASE-APPROVAL.md`, and
`DEFAULT-ATTEMPT-CENSUS.md` for the implemented boundaries. Original independent
semantic metrics and all-in cost stay null until valid evidence is supplied.
Historical mechanical catch and settled-PR noise screening must not be renamed
independent recall or FPR. Agent council reviews are engineering reviews only.

The owner/custodian must provide real independently blinded population and
candidate reviews, exact original candidate bytes with runner provenance, and
source-bound wallet/invoice/dispatch/CI reconciliation. Representative
multi-project default-product evaluation, sustained deployments, founder pain
measurement, and written pilot consents remain independent requirements of #73.
If historical candidate bytes cannot be recovered, use a newly declared real
cohort with fresh private custody; do not reconstruct the old cohort or call its
replacement identical. This patch does not automatically qualify such a cohort.

## Integrations used and deliberately not added

Used the existing GitHub Actions, Git CLI, pytest, Ruff, mypy, HTTPX/Melious router,
Hatchling build and existing evidence/stress tools. Added no production runtime
dependency, hosted arbitrary-code SaaS, new agent framework, billing service,
marketing claim or speculative product thesis. `repos.md` is a capability menu,
not a requirement to integrate every repository. No new external stack was
needed for these defects. Conflicting older research claims about hypothetical
model availability, competitors or "only product" positioning were not used as
verified launch facts.

## Reproduction

```sh
python -m pytest -q -o timeout=60 -o timeout_method=thread -p no:cacheprovider
python -m ruff check src tests scripts eval run_acceptance_verification.py run_v02_gate.py
python -m mypy src/jittest --ignore-missing-imports
PYTHONPATH=src python eval/ga73_reanalysis.py --check
PYTHONPATH=src python scripts/launch_gate.py --json launch-gate.json
python -m build
python scripts/check_distributable.py --dist dist --out dist/candidate-manifest.json
```

Live routing is opt-in, uses `MELIOUS_API_KEY` from the environment, incurs
provider spend and is not a GA metrics substitute. Credentials provided in chat
and attached instructions must be rotated before launch. Do not commit them.
Authoritative candidate results are the final-head CI and validation handoff,
not baseline timings or a source-level workflow review.
