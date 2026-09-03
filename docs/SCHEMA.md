# Verdict JSON Schema (Version 2.0) Stability Contract

This document defines the official **`schema_version 2.0`** stability contract for `jittest verify` evidence JSON artifacts.

All automated parsers, CI actions, and third-party verification tools can rely on these schema guarantees.

## Stability Guarantee

- **Backward Compatibility**: Fields defined in `schema_version 2.0` will never be removed or renamed within major schema version 2.x.
- **Strict Typos & Nullability**: Mandatory fields are guaranteed non-null unless explicitly marked nullable.

## Top-Level Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `schema_version` | `string` | Version identifier, strictly `"2.0"`. |
| `tool` | `string` | Generator identifier, strictly `"jittest verify"`. |
| `verdict` | `enum` | Overall test verdict: `"proven_catch"`, `"reproduction_catch"`, `"collection_catch"`, `"refuted"`, `"non_discriminating"`, `"inconclusive"`. |
| `proven_catch` | `boolean` | `true` if `verdict` is `"proven_catch"` or `"reproduction_catch"`; `false` otherwise. |
| `disposition` | `enum` | Fine-grained execution disposition: `"catching"`, `"head_failed_base_failed_latent"`, `"head_passed"`, `"head_uncollectable"`, `"base_uncollectable"`, or refusal status. |
| `provenance` | `object` | Execution environment and tool commit metadata (see below). |
| `sandbox` | `object` | Container and namespace isolation settings. |
| `base_execution` | `object` | Execution result of candidate test on base commit revision. |
| `head_execution` | `object` | Execution result of candidate test on head commit revision. |
| `rerun_agreement` | `boolean` | Flakiness verification across head reruns. |
| `wall_clock_s` | `number` | Total execution wall clock time in seconds. |
| `provider_cost_usd` | `number` | Total LLM model provider cost incurred during verification in USD. |
| `signature` | `object` | Cryptographic signature over receipt hash-chain (Ed25519). |

### `provenance` Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `repo_path` | `string` | Path to repository under test. |
| `base_sha` | `string` | 40-character hex commit SHA for PR base revision. |
| `head_sha` | `string` | 40-character hex commit SHA for PR head revision. |
| `test_file_name` | `string` | Basename of the verified test file. |
| `test_file_sha256` | `string` | 64-character SHA-256 digest of verified test file source. |
| `tool_commit_sha` | `string` | 40-character hex commit SHA of `jittest` tool executing the verification. |
| `tool_branch` | `string` | Branch ref of `jittest` tool executing the verification (`git rev-parse --abbrev-ref HEAD`). |
| `tool_dirty` | `boolean` | Dirty state flag of `jittest` repository (`git status --porcelain`). |
| `tool_tree_sha` | `string` | 40-character hex tree SHA of `jittest` tool. |
| `rel_path` | `string` | Relative path within monorepos (default `"."`). |

### `signature` Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `algorithm` | `string` | Asymmetric key algorithm, strictly `"Ed25519"`. |
| `verifying_key` | `string` | 64-character hex Ed25519 public key. Legacy receipts (v0.3.x) use `public_key`. |
| `value` | `string` | Base64-encoded Ed25519 signature over canonicalized payload string. |

## Verification & Recomputation Protocol

To verify an evidence receipt against this schema:
1. Run `jittest verify-receipt <artifact.json>`.
2. Verifies cryptographic Ed25519 signature integrity against `verifying_key` carried in the receipt.
3. Validates top-level schema contract (`schema_version`, `tool`, valid 6-verdict enum, and `proven_catch` invariant).
4. Optionally authenticate signer identity with `--expected-signer <key_or_fingerprint_or_allowlist>`.
5. Optionally verify provenance consistency with `--expected-base`, `--expected-head`, `--expected-test-sha256`, and `--expected-repo`.
