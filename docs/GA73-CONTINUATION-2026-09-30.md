# GA-73 continuation: engineering evidence, not a GA declaration

## Audit

- **Done:** paired execution/receipt CLI, zero-dependency core, required sandbox refusal, health/readiness probes, JSON logging and tracing were already present.
- **Broken -> fixed:** billing refusals retried as rate limits, direct endpoint namespaces, missing Melious price provenance, discarded truncation usage, untyped malformed/server responses, optional-router transient server retries, and isolated engine forced to use the mini-runner even when a trusted image contained pytest.
- **Partial:** bounded live provider reliability. The retained runs include failures; one later burst is not a sustained availability SLO.
- **Missing:** sample-qualified catch/FPR and billing-reconciled USD per real PR, external adoption/payment evidence. These cannot be replaced with fixture results or instrument readiness.

## Frozen and retained evidence

Unchanged main: 1,257 tests passed, 9 skipped, 210 subtests passed. Recovered attachment regression file: 19 failed, 7 passed before fixes. Attachment redactions had damaged six pytest parameter decorators; these were restored before measuring.

An earlier complete eight-worker suite passed 1,311 tests, with 9 skipped and 210 subtests. A later 1,316-test run exposed a subprocess import-path failure (ModuleNotFoundError), not a process cleanup finding; the complete suite then passed with an explicit absolute source path: 1,316 passed, 9 skipped, 210 subtests in 91.24 seconds under eight-worker contention. No proc fix was attempted. Ruff passed over src/tests/scripts/eval; mypy passed over eight changed production modules.

Four baseline live completions succeeded. Subsequent 100-worker runs retained in `docs/evidence/ga73-20260930/` completed 88, 96 and 92 exact responses respectively. Diagnosed failures included provider read timeouts and HTTP 503. After bounded transient-server retries, the next 100-worker run completed all 100 exact responses (25 per requested model); P50/P95/P99 were 4.682/8.538/8.657 seconds. One Qwen call needed two retries. A 30-second request deadline was used; this is not a hard wall-clock cancellation guarantee.

The latest persona harness passed: 120 synthetic personas across 20 behavior types, 100 workers and 1,000 burst requests. P50/P95/P99: 118.142/149.349/156.203 ms; throughput 797.9 requests/s; sampled RSS floor/ceiling 25.9/38.8 MiB; recovery 1.3 ms. No harness panics, unexpected results, readiness-registry drift or surviving server thread were observed. This is not proof of zero leaks across arbitrary workloads.

## Premortem and scope

1. JIT/process races: existing process hardening remains unchanged; exercise the real contention harness. No sixth proc fix cycle was attempted.
2. Thread starvation: single publication of the shared HTTP client, bounded retries and typed errors. No sustained production throughput claim.
3. Nondeterministic drift: frozen corpus SHA, explicit fixed seed, retained failed runs, immutable runtime identity in CI artifacts.
4. Financial misreporting: exact provider/model pricing and explicit finite FX; billing refusals stop generation. Token/list-price estimates are not wallet statements. Failed requests may have unobserved spend and response guards can overshoot by a request.
5. Unsafe evaluation: no corpus setup scripts, Dockerfiles or dependency installers run on host in the new smoke. Pytest probing and candidate execution remain confined; required isolation refuses without a daemon.

## GA-73 B1

The new `ga73-isolated-smoke` workflow is bounded to three pinned PySnooper revisions. It builds a trusted pytest runtime from a resolved official Python digest, pins the resulting image through a local CI registry, verifies image inventory, runs Docker canaries and captures raw paired outcomes. It refuses a green result without actual base/head execution evidence and healthy collection. A successful smoke establishes instrument validity only, not the three GA numbers.

Melious list rates were rechecked against https://melious.ai/pricing. Official ECB daily XML was dated 2026-09-29 with USD/EUR 1.1355; the workflow retrieves dated official FX rather than hardcoding it.

## Integrations used

Existing GitHub Actions, Docker, pytest and optional httpx transport were reused. `repos.md` was reviewed; no additional orchestration framework was needed or introduced. Existing CodeQL remains a CI gate. Core runtime dependencies stay empty. The provider credential is an encrypted dedicated repository secret, supplied only to the paid smoke step, never a build argument or corpus container environment.

**Launch status:** do not close GA-73 or claim production readiness on the strength of these engineering checks. Audit the actual smoke artifact, then complete the predeclared larger real-corpus evaluation, independently adjudicated settled-PR sample, billing reconciliation and external pilot gates.


## Actual real-daemon findings, first smoke

The first paid smoke ran on a real Docker daemon and **failed correctly**: 17 of 30 candidate dispositions were `head_uncollectable`, with no base/head execution pair. All three bugs made real model requests. No catch-rate conclusion is published from this environment-broken run.

Root cause read from frozen corpus source: PySnooper revisions import `Mapping`/`Sequence` from `collections`, removed in Python 3.10; the image incorrectly used Python 3.12. The oldest revision also declares decorator/future/six, although BugsInPy's per-bug requirements metadata is empty. The corrected **research-only** image matches the declared Python 3.8 specimens and explicitly pins these runtime packages. Jittest itself stays on the supported Python 3.12 host. Legacy/EOL Python is confined offline for historical measurement, not promoted as a production runtime. Safety rules were not relaxed to admit rejected write/interpreter operations.

Current-head real-daemon Option C, public phase-boundary and registry-live proof workflows ran successfully; raw artifacts were retrieved for independent inspection. CI also exposed optional-httpx collection in the new tests; zero-dependency discovery now skips that optional test module explicitly, while the funded smoke step installs the extra and executes it.

New authoritative evidence: Melious documents `billing_cost.credits` as an exact decimal EUR equivalent and `paid_with` as the actually debited balance. Response billing is now captured with decimal arithmetic and propagated into reports/evaluation rows. Energy coverage is not misreported as a cash credit debit; missing/invalid metadata withholds totals. A real Flash probe returned EUR 0.0000031 with `paid_with=credits`. This closes a previously missed accounting instrumentation gap, not the qualified USD-per-real-PR evaluation itself. Source: https://melious.ai/docs/concepts/pricing

Billing scope is received successful responses only; a complete billing block does not certify that every failed/timed-out request was unbilled. Preserve transport failures and reconcile separately.

## Corrected B1 result and billing-aware routing

Workflow run 36625841260 passed on commit 69fe845. All three historical specimens were measured; seven candidates produced real base/head execution pairs, zero of sixteen dispositions were head-uncollectable. Two specimens had mechanically catching candidates. This three-specimen smoke is not a qualified GA catch rate. Raw artifact: docs/evidence/ga73-20260930/ci-accepted/ga73-smoke.json.

A second successful 100-worker live burst completed 100/100 exact routing checks, 25 per requested model, with valid billing metadata on all received responses. P50/P95/P99: 4.533/9.820/9.981 seconds; throughput 9.092 calls/s; RSS 20,772 to 41,892 KiB; threads one before and after. Exact observed credit debit was EUR 0.0322061, USD equivalent 0.03657002655 at the recorded FX. This is the cost of tiny routing calls, not USD per real PR; failed/unreceived responses remain outside this sum.

CI's sensitive-information alert was addressed rather than dismissed: full preflight JSON is no longer printed; provider error bodies and exception details cannot be echoed into terminal diagnostics. A credential-echo regression failed before the fix and now passes. Malformed JSON/token/billing metadata are bounded and typed, with unsafe decimal exponents rejected; longest model-name matching prevents mini variants being priced as their parent.

## Downstream predeclared pilot

The larger paid pilot is explicitly triggered once: 25 frozen BugsInPy specimens from PySnooper/tqdm/youtube-dl, followed by 40 Python-changing settled merges from the approved youtube-dl repository. The runtime is declared in artifacts; dependency compatibility is judged by collection, not asserted. Raw checkpoints retain full commit identities, execution funnel, claim source/tests, successful-response decimal billing, token estimates, and refusal/failure denominators. Response-accounted limits are USD 2 for bugs and USD 1 for merges; these are not a provider-side reservation.

Publication requires the predeclared sample floors, at least 80% bug completion, healthy collection, actual execution pairs, and independently adjudicated ground truth. The settled-merge result is a screening proxy, never definitive FPR. A failed qualification remains a failed workflow with raw outcomes retained. No current claim of GA-ready, market traction, or clean production SLOs is made.
