# Error and Exit-Code Contract

Every refusal is machine-readable and names the one thing to do next. The
table below is the single source of truth and is asserted by
`tests/test_cli_explain.py` against `jittest.explain.EXIT_CODES`.

## `jittest verify-receipt` and `jittest explain`

| Exit | Code | Meaning | Hint |
|---|---|---|---|
| 0 | `ok` | every requested check passed | cite the receipt by `test_file_sha256` and `head_sha` |
| 2 | `signature_invalid` | payload tampered or signature block malformed | fetch the original artifact from the CI run |
| 3 | `signer_untrusted` | signer not in allowlist, or unverified under `--strict-signer` | pass `--expected-signer` with the fingerprint from `docs/KEYS.md` |
| 4 | `schema_invalid` | schema invalid or unsupported version | regenerate with jittest >= 0.3.5; 2.0 receipts prove integrity only |
| 5 | `semantic_invalid` | a verdict invariant is violated | treat the verdict as unproven; rerun `jittest verify` |
| 6 | `provenance_mismatch` | base/head/test/repo differ from what was expected | compare `--expected-base/--expected-head` with the PR SHAs |
| 7 | `not_confined` | execution was not inside a sandbox boundary | rerun with `JITTEST_SANDBOX=required` on a runner with docker/podman/bubblewrap |

Precedence is top-down: a tampered receipt is reported as `2` even if it is
also unconfined.

## `jittest explain`

```
$ jittest explain receipt.json
jittest explain: receipt.json
  verdict      : proven_catch (the candidate test PASSES on base and FAILS (assertion) on head: it catches the change)
  signature    : valid; signer TRUSTED
  schema       : VALID (version 2.1)
  semantics    : consistent
  provenance   : MATCHED; github.com/org/repo 8c753b6dc91b..e2cd1672a62a
  execution    : CONFINED; sandbox backend docker, image python:3.13-slim, network denied True
  result       : OK (exit 0, ok)
  hint         : nothing to do; cite the receipt by its test_file_sha256 and head_sha.
```

`jittest explain --json` is the stable machine contract (`explain_version: 1`,
keys are additive-only). Agent vendors and dashboards should consume this, not
the text form.

## `jittest doctor`

Doctor prints `sandbox: NONE ... WILL REFUSE` whenever no docker, podman or
bubblewrap is usable. On Windows and macOS this is the normal state outside
Docker Desktop; it is stated so that a green doctor is never mistaken for a
confined runner.
