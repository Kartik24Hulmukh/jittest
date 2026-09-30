# Dispatch validator follow-up — bounded refinement

Parent source-preparation commit: `5108ddb849785d395a61953e82e312f4a1a97895`.
Original main baseline remains `6ca6698444718bdb58316d76f8c92ca9deccfacb`.

The parent independently reviewed source and identified schema validators that
were less strict than the handoff language. These concerns were confirmed before
source edits:9 newly added owned schema tests produced40 failure instances and
4 AttributeError instances (including subtests). Two positive compatibility
cases already passed. The failure log and pre-edit source/test hashes are in
`evaluation-validator-followup.json`; no provider or owner data was used.

## Bounded change

Only `_billing.py` and its dedicated test file changed, plus these two additive
follow-up evidence files. `llm.py` is byte-unchanged from the original preparation
commit; no transport retry/budget behavior or caller wiring changed.

The summary now refuses malformed non-object events with ValueError, unsupported
schema version/types, present-but-invalid identifiers/stage, malformed or naive/
non-UTC dispatch timestamps, malformed HTTP statuses, incompatible body/transport
observations and invalid parsing progress. Nondispatch cache/guard/predispatch
records cannot claim response IDs, status, receipt body or dispatch timestamp.
A cache decode result remains a nondispatch observation, not a provider body.

Noncredit billing requires an actually received parsed response/error body and
finite nonnegative documented EUR equivalent; it cannot turn timeout/absent-body
or NaN into apparently complete expense. Observed credit debit must agree with
its documented equivalent and the received/parsed body phases. Unknown amounts
remain null. Identifiers may genuinely be missing None, counted as missing—not
fabricated. Positive tests preserve absent attribution, valid noncredit payment
and two distinct dispatches in one invocation both using retry_index0 (legitimate
n>1 batches). No ungrounded uniqueness restriction on retry indices was added.

A finite received-response amount still does not reconcile a wallet, invoice,
whole-system attempt census or CI expenses. Source-generated client ledger
coverage remains opt-in and client-local, not whole-stage coverage. Signed
external attestation and private invoice allocation remain absent.

## Final checks at a frozen current source

- Combined selected pytest:194 passed,1 optional collection skip,62 subtests
  passed,23.98seconds. Same14-file selection as evaluation-implementation.md.
- Dedicated system-Python unittest discovery:33 passed without pytest required.
- Scoped Ruff and git diff --check passed.
- Source hashes frozen before final combined tests verified unchanged after it.
- No full suite, Docker, foreign corpus, paid calls or deployment reproduction.

This is bounded refinement round4 following the three prior source/test rounds,
within the maximum five-cycle guard. No retry-policy change, PR/merge/tag/release
publication, outreach, independent human labeling or reconciled expense claim.

Integration owner must apply this follow-up after the original preparation
commit and run final accepted integration/full-suite gates on the combined tree.
The earlier public preparation commit remains immutable. Issue73 remains open.
