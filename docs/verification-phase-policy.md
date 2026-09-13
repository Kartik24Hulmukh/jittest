# Verification phase policy (schema 2.1 additive evidence)

`verify_test` applies readiness before and output inspection after every normal
candidate execution: base, head, the supported head rerun, unchanged health tests,
and fallback assertion probes. Required-mode typed refusals propagate through
health-probe fallbacks; they are never converted to a successful fallback.

The signed `verification_phases` array records phase, revision, test digest,
dependency-list digest, readiness observation, outcome, exit code, stdout/stderr
digests and output observation. An absent supported requirements manifest is
explicitly `evaluated=false`, not a successful environment certification.
The existing `readiness` alias remains BASE-only; `output_guard` remains first
HEAD-only for compatibility. Neither alias is an aggregate policy verdict.
A refused verification raises the existing typed refusal; partial phase records
are not currently exported into the CLI refusal receipt.

## Limits — not a GA certification

- Readiness is a dependency-name presence check, with simplistic lock comparison.
  It is not a PEP 508 resolver, version/marker/extras/ABI or transitive-dependency
  proof. It checks the first supported requirements manifest, not every packaging
  format. `required` enforces this limited predicate only.
- Scanning assumes the runner has stopped descendants. Scans do not create
  confinement; unconfined runs remain unconfined. Real-daemon cleanup proofs and
  hostile-writer tests are separate acceptance gates.
- An execution exception does not produce a successful phase/output record.
- The legacy integrity record binds candidate code and initial output hashes;
  it is not a whole-repository reproducible-build attestation. Phase observations
  are covered by the outer Ed25519 receipt signature.
- The current API performs at most one HEAD rerun. This change does not redefine
  the `reruns` parameter or claim arbitrary-count stress coverage.

Tracked follow-up: issue #194 remains open for precise readiness semantics,
phase-specific integrity/completeness and real-daemon public-path evidence.
