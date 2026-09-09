# Privacy and Telemetry

JitTest has **no phone-home telemetry**. Nothing leaves the machine that runs it
unless you configure a model provider, in which case only the prompt built from
the diff and the redacted source context is sent to that provider (see
`src/jittest/redact.py`).

## What `--telemetry-json` writes

`jittest run --telemetry-json <path>` appends one JSON object per model request
to a **local file you name**. Fields: model, prompt/completion token counts,
price estimate, cache hit, wall clock. No source code, no diff text, no
hostnames, no user names. You can delete the file at any time; nothing reads it
except `jittest stats`.

## What a receipt contains

A receipt (`docs/SCHEMA.md`, `schemas/receipt-2.1.schema.json`) carries:

| Field | Contains | Does not contain |
|---|---|---|
| `provenance.repo_path` | a display path; `<USER_DIR>` replaces the home directory | your username |
| `provenance.repo_canonical` | `github.com/org/repo` or `local:<hash>` | remote credentials |
| `*_execution.stdout_sha256` | a digest of test output | the output itself |
| `provenance.test_file_sha256` | a digest of the candidate test | the candidate source |
| `sandbox.*` | backend name, image reference, isolation flags | container IDs |
| `signature.verifying_key` | the public half of the signing key | the private key |

Receipts are safe to publish. The CI lint step verifies that everything under
`receipts/` is cryptographically valid and `redact.py` scrubs absolute user
paths before signing.

## Keys

The Ed25519 signing seed lives in `~/.jittest/signing_key` (mode 0600) or
wherever `JITTEST_SIGNING_KEY` points. It is never written into a receipt, a
log, or telemetry. See `docs/KEYS.md`.

## Model providers

When `JITTEST_API_KEY`/`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is set, the prompt
(diff hunks plus redacted context) goes to that provider under their terms.
`--dry-run` and `jittest oracles` need no key and make no network calls.
