# September 30 hardening continuation — bounded verifier preview

## Decision and scope

Engineering preparation, not GA or publication. The implementation starts from `bf642162a3059b3ec116c2d0db9333892fa6c9f7`. The published package/tag mapping remains unchanged. No release tags, registry upload, public outreach, customer consent or independent human labels were created. No adoption, payment, retention or 100× growth was demonstrated.

The governing attachment and supplied launch/correctness/evaluation councils are scope inputs, not acceptance evidence. Source, actual test outcomes and immutable raw artifacts control the conclusions. No new platform or strategy stack was added.

## Frozen baseline and completed changes

- The unedited baseline suite ran: **1,322 passed, 9 skipped, 210 subtests passed**, 155.92 seconds. Existing passing tests did not cover the reproduced consumer-contract failures. The correctness council's new baseline had **20 failures out of 22 acceptance cases** before fixes.
- Exact PR event base/head resolution includes blank composite inputs; missing Git objects and failed diffs are explicit refusals, never evidence of zero changed tests.
- Action independently consumes producer receipts with externally resolved base/head/test/repository expectations. This is not independent enrollment of a trusted production signer.
- Non-assertion errors and missing actual repeated assertion executions cannot create behavioral proven catches. Malformed signed receipt types fail cleanly. Test fixtures were strengthened rather than weakening validation.
- Action summaries are independent of comment availability; artifacts upload with `always()` even when policy fails.
- Clean wheel installs now retain tool build identity. Wheels and sdists carry source SHA and dirty-diff identity, and their package bytes/build metadata must agree. The exact-wheel rehearsal executes only its own harmless host fixture, checks a separately fixed public fixture signer and external PR provenance, and exercises tamper/wrong-head/wrong-signer/confinement negatives. This is not a real-daemon confinement proof.
- Release preparation tests optional transport dependencies, checks the distributable, and prevents GitHub release/floating-tag advancement before exact public registry bytes are verified. Manual rehearsal cannot publish. The publisher Action is pinned by immutable commit. New versions/publication still require separate owner approval.
- Onboarding, runtime configuration and isolation docs were corrected to match actual supported inputs, mutable worktree/tmpfs limits, and signed-confinement claims.

## Real production routing: preserve failures

User-authorized production requests used the existing Melious transport and supplied Bearer credential; no credential was placed in source, artifacts or containers. Four model baseline jobs succeeded. A 100-worker burst then completed **92/100**: all eight failures were GLM-5.3 read timeouts; each other model completed 25/25. This failed run is retained, not discarded.

After per-model backpressure (default eight concurrent dispatches, queue wait counted against budget, slots always released), the next 100-worker burst completed **100/100** exact replies, 25 per requested model. P50/P95/P99 were **2.555/6.932/8.104 seconds**, throughput **11.246 jobs/second**, RSS start/end **20,852/38,564 KiB**, and active threads returned from one to one. Weak slot references prevent completed arbitrary model identifiers accumulating process-lifetime scheduler state.

This is a finite, non-randomized retest, not proof that backpressure alone caused every improvement or a sustained availability guarantee. HTTP phase timeouts are not hard wall-clock cancellation. No cross-model substitution hides failed GLM calls. Unknown charges for failed/unreceived requests remain unknown.

Received-response credit debits were EUR **0.0013845** (four-job baseline), **0.0315602** (92 received responses in failed burst), and **0.0328387** (100 received responses in bounded burst). All received billing entries in those artifacts are complete. These are not wallet reconciliation, total expense, or USD per PR; routing pings are not PR evaluations.

## Synthetic abuse, not human adoption

Fixed seed 20260930, 100 workers, 1,000 probe burst requests and **120 synthetic persona instances across 20 behavior kinds**. Baseline and candidate both passed their finite harness; neither represents actual human users or exhaustive adversarial testing. Candidate: no unhandled panics, no unexpected statuses, no readiness registry drift, server thread stopped, health recovery **0.998 ms**, RSS floor/ceiling **25.9/38.4 MiB**, burst throughput **608.4 requests/second**, P50/P95/P99 **157.151/197.818/215.428 ms**. This run overlapped other test processes and is not a latency improvement claim. Recovery is distinct from request latency and process admission wait.

## Premortem: five risks and remaining limits

1. **JIT/checkout race and wrong identity:** bind to resolved event commits; no checkout-HEAD fallback when a PR identity is known. Real Git/entrypoint fixtures verify the pair. Remote runner/event trust and repository permissions remain deployment responsibilities.
2. **Starvation and provider saturation:** per-model dispatch bounds and budgeted queue waits; existing subprocess admission limits remain. A child's post-spawn timeout is not a whole-job queue deadline; fairness and sustained SLOs require operational measurement.
3. **Nondeterministic/runtime drift:** actual rerun records and BASE runtime precedence, image inventory and embedded distributable identity. Fresh real-daemon/registry proof must be supplied by CI; historical passes are not present deployment evidence.
4. **False-green failure paths:** missing objects/diff errors, required sandbox absence, invalid receipts and policy failure are visible refusals with summaries/artifacts. Advisory intentionally does not promise conventional regression blocking.
5. **Self-invalid or forged trust claims:** strict schema/semantic checks and externally expected provenance, plus tamper/signer negatives. Signed confinement is an authenticated producer statement, not independent daemon attestation or universal safety. Production signer enrollment must be externally governed.

## Issue #73: reduced gap, not fabricated closure

`../ga73-reanalysis-20260930/` preserves all original cohort bytes and adds explicit oracle-entry, response and paired-execution denominators. Mechanical 16/25, surfaced 12/25 and conditional screening 0/40 remain unchanged. True FPR and validated default-product recall remain unmeasured. A public unfilled adjudication template and a total-cost reconciliation contract identify precisely what is missing; retained archives cannot recover original missing stochastic candidates.

Independent semantic adjudication with adequate candidate/context material, failed-call/wallet/CI reconciliation, representative default-verifier evaluation, real maintainer adoption and founder problem-value experiments remain genuine gates. Agent councils are not independent human labels or customer consent. Keep #73 open for those criteria; do not silently turn a GA issue into preview certification.

## Existing tooling and repos.md integrations

Used the project's existing stdlib Git/HTTP/Ed25519/test runner, `httpx` optional transport, pytest/hypothesis regression infrastructure, Hatchling build hooks, and GitHub Actions. No additional repository from `repos.md` was imported: existing components supported the bounded repairs; introducing an orchestration/platform stack would add risk without evidence of launch value.

## Final acceptance

Final source suite, exact committed artifact proof and real-daemon CI status are recorded separately when they actually finish. Skipped container tests are not passed tests. No "fully production ready", "fixed and shipped", broad-GA, zero-FPR or unlimited 100× reliability claim follows from this report.

### Completed local acceptance before PR

The frozen full suite passed **1,414 tests, 10 explicit skips and 214 subtests** in 170.70 seconds. Fresh-wheel installation/receipt acceptance passed separately (the optional full-suite wheel-path test was one of the skips). The independent refreshed reviewer selection passed 173 tests, with six optional-dependency skips. Two intermediate suites with six compatibility failures each are retained; they ran during fixture reconciliation and are not release evidence. Positive fixtures now record required observed reruns; the former TypeError behavioral-proof expectation was corrected to an explicit non-assertion refusal; filename uniqueness now uses real Git and execution instead of a fake producer.

The installed Option-C gate is wired to an actual registry/daemon-dependent CI lane, with no skip-success path. Its offline no-daemon refusal and workflow contract tests passed; fresh real-daemon results are still pending, not inferred from this workspace.

Raw failure logs are byte-preserved in `raw-failure-logs.zip`; `raw-failure-log-sha256.json` binds each original member. Archiving avoids reformatting forensic whitespace.

### Fresh hosted daemon proof and CI-discovered test-framework defect

Actual run https://github.com/Kartik24Hulmukh/jittest/actions/runs/36732701721 completed all three jobs: registry-live, wrapper/phase proof, and installed-wheel proof. The installed-wheel record is `RUN`/passed, 31.232 seconds, pip25.0.1, authoritative Python image digest `sha256:44ff437bba879d4941b710a369a8f19266aea34b29002807f0c487fabc9eec9b`. Both-revision isolation canaries, BASE authority/HEAD override, fresh signed assertion catch plus external consumer, real timeout/descendant cleanup passed; running containers before/after were empty. Raw JSON and full wheel artifact are preserved. The artifact was built at the hosted PR merge checkout160291d09bef2c7a7491dead4d92eec69fe68c97; local committed buildfc3ffa971a66d581c1f4d316ecba5bd02d5ec0e7 has a different provenance-bearing wheel hash, not a byte-identity claim between those Git revisions.

The clean committed local full suite passed **1,416 tests,10 skips,214 subtests** in169.43seconds. Hosted zero-dependency discovery then exposed two newly added pytest-only fixture modules importing pytest unconditionally. This was a test-framework packaging compatibility failure, not a passing gate. Imports now explicitly skip those optional fixture suites in stdlib-only discovery; the full pytest lane still runs them. Final-head hosted CI must pass before merge.
