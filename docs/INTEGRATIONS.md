# Integrations

The integration surface is the **receipt**, not the CLI. Anything that can read
JSON and verify Ed25519 can consume JitTest output; `schemas/receipt-2.1.schema.json`
is the published contract.

## GitHub Actions (consumer)

```yaml
- uses: Kartik24Hulmukh/jittest@main   # pin to a SHA in production
  with:
    sandbox-mode: required            # default; refuses when no backend is usable
- run: jittest explain jittest-evidence/receipt.json --require-confined --strict-signer \
         --expected-signer docs/KEYS.md
```

## Verify a receipt offline (zero dependencies)

```bash
pipx run jittest verify-receipt receipt.json --json --require-confined
# exit codes: docs/ERRORS.md
```

## Validate against the JSON Schema (any language)

```bash
pip install check-jsonschema
check-jsonschema --schemafile schemas/receipt-2.1.schema.json receipt.json
```

Node:

```js
import Ajv2020 from "ajv/dist/2020.js";
const ajv = new Ajv2020();
const validate = ajv.compile(require("./schemas/receipt-2.1.schema.json"));
console.log(validate(receipt) ? "schema ok" : validate.errors);
```

Schema validity is necessary, not sufficient: the signature and semantic
invariants (`docs/SCHEMA.md`) are checked by `jittest verify-receipt`.

## Agents and MCP

An agent that proposes a PR should attach the receipt and quote
`jittest explain --json` fields `verdict`, `checks.execution_trust`, and
`provenance.head_sha`. An MCP tool wrapper is designed but not built; it would
expose exactly `explain_receipt()` and nothing that executes code.

## Trusted runtime images (Option C)

```toml
[tool.jittest.runtime]
image = "ghcr.io/kartik24hulmukh/jittest-pilot-requests@sha256:<digest>"
```

See `docs/RUNTIME-IMAGES.md`; the pilot image source is `docker/pilot-requests/Dockerfile`
and `scripts/prove_option_c.py` records whether it has actually run on a daemon.
