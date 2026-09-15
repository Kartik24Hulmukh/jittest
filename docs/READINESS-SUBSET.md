# Public readiness: supported subset and remaining GA work

The public `jittest verify` phase preflight retains installed versions from both
provisioner freeze lists and distribution/version mappings. Previously it reduced
both to names: `Flask>=3` with `Flask==2` could pass even in required mode.

## Current contract

Set `JITTEST_READINESS=required` for fail-closed enforcement. The default remains
`observe`: an unsupported input records `evaluated: false`, never `ok: true`,
and does not itself stop candidate execution. A supported but incompatible input
records `ok: false` in observe mode and refuses before execution in required mode.

Supported: ordinary distribution names (PEP 503 normalized), numeric final-release
versions, and comma-separated `==`, `!=`, `<`, `<=`, `>`, `>=` constraints.
Blank lines and comments are allowed. A provided requirements.lock is checked too.

Explicitly unsupported on this public preflight: includes/constraints directives,
editable installs, malformed or unfinished lines, markers, extras, direct URLs,
wildcards, compatible/arbitrary equality, and pre/dev/post/local/epoch versions.
These refuse in required mode rather than being silently skipped or compared with
an incomplete PEP 440 algorithm. Unparseable inventory and conflicting duplicate
versions also refuse. Error metadata does not echo dependency URLs or input text.
This intentionally favors safe false refusals over false compatibility assurances;
it is not full packaging support. Legacy library parsing remains permissive for
existing diagnostic callers; the public boundary explicitly opts into strict parsing.

## Not a GA certificate

- No supported requirements manifest still records an unevaluated phase. This
  patch does not add pyproject/setup.cfg discovery or prove transitive/ABI compatibility.
- A trusted container inventory bound to its digest is still absent; Option C
  currently reports an empty inventory. Do not infer compatibility from that.
- Marker evaluation needs target, not host, metadata. Supporting markers merely
  by evaluating them on the launcher would introduce another false-green path.
- The legacy readiness helper's version parser is not a standards-complete resolver.
  The public path avoids unsafe semantics; replacing that parser remains separate work.
- No official receipts have been regenerated and no efficacy/cost claims are made.

## Regression validation

`python -m pytest tests/test_readiness_fail_closed.py tests/test_p0_public_path.py tests/test_readiness_pep508.py tests/test_phase_boundaries.py tests/test_p0_gates.py`

Tests cover dict/freeze version conflicts, supported ranges, unsupported packaging
syntax, malformed inventory, observe semantics, lock directives, and prevention of
candidate execution after a required-mode conflict.

Reference: https://packaging.python.org/en/latest/specifications/dependency-specifiers/

Related: #198 (partial hardening only; keep open).
