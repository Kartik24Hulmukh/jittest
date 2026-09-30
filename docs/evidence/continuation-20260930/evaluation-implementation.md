# Billing dispatch measurement — source-preparation handoff

Base source: `6ca6698444718bdb58316d76f8c92ca9deccfacb`.

Implemented only `src/jittest/llm.py`, `src/jittest/_billing.py` and the new
`tests/test_billing_dispatch_contract.py`. The related additive evaluation
reports do not replace historical cohort bytes or rates. No commits in unrelated
modules, paid provider calls, foreign corpus execution, PR/merge/tag/release or
outreach were authorized for this increment.

## Behavior

Successful HTTP response billing is captured before completion or usage parsing.
Typed content/usage errors remain errors; token counters/guards/retry policy remain
unchanged. `provider_response_count` may now exceed `usage.calls` when a billed
body fails subsequent parsing. The former means observed object billing; the
latter retains its prior token-accounted successful-completion scope. It is not
an actual-dispatch count or hard wallet spending limit.

Opt in with a caller-owned list passed as `dispatch_ledger` to HTTPLLM. The client
appends one event for each actual urllib attempt, not for each generator loop.
Each complete invocation receives a local ID; each actual attempt a distinct
local dispatch ID. Recognized provider request-ID response headers are separate.
Cache lookup, corrupt-cache parse failure, guard refusal and predispatch error
are tracked without invented dispatch IDs. Empty/invalid body, transport loss
and timeout retain unknown credit debit as null. Parsed billed HTTP errors are
observed ledger evidence, not successful completions. Successful response
billing aggregate remains distinct from these error-response ledger observations.
Energy/noncredit values never become observed credit zero.

`dispatch_context` may carry explicit run_id, target_id and generator/assessor
stage. No prompt inference occurs; absent or invalid fields are null. Prompt,
body, arbitrary headers, URLs, credentials and error text are not stored. Exact
API-key echoes in IDs are filtered. Sanitized provider-ID handling is not a
universal DLP guarantee; caller IDs must be actual identifiers, never secrets.

`dispatch_ledger=None` is the default: no ledger retained. Its external owner
controls retention and any private export. A list is not crash-durable, atomic
across processes or a proof of complete system coverage; shared concurrent use of
an HTTPLLM instance is not supported by this work. Non-urllib backends and callers
are not silently instrumented. Complete per-stage/PR attribution needs separately
approved caller integration, and private invoice allocation remains external.

`summarize_dispatch_ledger(events)` validates IDs, retries, finite nonnegative
observed amounts and unknown/null consistency; counts actual/retry dispatches,
known/missing invocations/context/request IDs, unfinished transport and parse
failures. Observed EUR is only a subset. Wallet status remains false; reconciled
provider USD and CI expense remain null. No FX receipt or invoice join is invented.

## Frozen adverse evidence

Legacy billing baseline:11 unittest tests passed. New18-test suite failed with
21 error instances (including subtests); most represent missing ledger API,
while the real-localhost billed malformed-content case reproduces original
charged-response evidence loss. Original hashes and log hashes are in
`evaluation-baseline.json`. No mock is substituted for the HTTP request path in
the dedicated fixture tests; environment patching only selects the owned
localhost specification endpoint. Charges in these fixtures are synthetic.

## Final validation

- Combined selected pytest tests:185 passed,1 skipped,13 subtests passed,24.20s.
- Dedicated system-Python unittest:24 passed without pytest/runtime extras.
- Ruff scoped source/test check passed; `git diff --check` passed.
- No full-suite, installed-wheel, Docker or sustained-deployment rerun claim.
- Three bounded source/test refinement rounds; no infinite retry or paid sweep.

Exact selected invocation:

```bash
python -m pytest tests/test_billing_dispatch_contract.py tests/test_provider_billing.py tests/test_transport_retry.py tests/test_request_ceiling.py tests/test_rate_limit.py tests/test_production_transport.py tests/test_cost_accounting.py tests/test_model_unavailable.py tests/test_http_timeout.py tests/test_pipeline.py tests/test_measurement.py tests/test_nothing_analysed.py tests/test_git_failures.py tests/test_units.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_billing_dispatch_contract.py'
ruff check src/jittest/llm.py src/jittest/_billing.py tests/test_billing_dispatch_contract.py
git diff --check
```

The optional skip and final source/result hashes are in `evaluation-results.json`.

## Integration acceptance

Cherry-pick only the preparation commit. Re-run the scoped selection and the
integration owner's full accepted suite against the combined tree. Keep #73
open: independent human labels/field rates, wallet/CI totals, sustained deployment
and actual product value remain unmeasured. Next smallest separately scoped
facility is the denominator-preserving default Action census described in
`evaluation-council.md`, not another generator/routing cohort.
