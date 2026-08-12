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
| `verdict` | `enum` | Overall test verdict: `"proven_catch"`, `"refuted"`, `"non_discriminating"`, `"inconclusive"`. |
| `proven_catch` | `boolean` | `true` if and only if `verdict == "proven_catch"`. |
| `disposition` | `enum` | Fine-grained execution disposition: `"catching"`, `"head_failed_base_failed_latent"`, `"head_passed"`, `"head_uncollectable"`, `"base_uncollectable"`. |
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
| `public_key` | `string` | 64-character hex Ed25519 public key. |
| `value` | `string` | Base64-encoded Ed25519 signature over canonicalized payload string. |

## Verification & Recomputation Protocol

To verify an evidence receipt against this schema:
1. Run `jittest verify-receipt <artifact.json>`.
2. Ensure `schema_version` equals `"2.0"`.
3. Confirm Ed25519 signature validation succeeds against project public key `74545a9c15ce0602720de6f2e0a03fb95399aed8085291f62490874a1bb9a130`.
