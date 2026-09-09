# Verdict JSON Schema (Version 2.1) Stability Contract

This document defines the official **`schema_version 2.1`** stability contract for `jittest verify` evidence JSON artifacts.

All automated parsers, CI actions, and third-party verification tools can rely on these schema guarantees.

## Stability Guarantee

- **Backward Compatibility**: Fields defined in `schema_version 2.0` and `2.1` will never be removed or renamed within major schema version 2.x.
- **Strict Typos & Nullability**: Mandatory fields are guaranteed non-null unless explicitly marked nullable.
- **Legacy Compatibility**: Historical receipts with `schema_version: "2.0"` are verified as `VALID_LEGACY` with `execution_trust: UNKNOWN`.

## Top-Level Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `schema_version` | `string` | Version identifier, strictly `"2.1"` (`"2.0"` supported as legacy). |
| `tool` | `string` | Generator identifier, strictly `"jittest verify"`. |
| `verdict` | `enum` | Overall test verdict: `"proven_catch"`, `"reproduction_catch"`, `"collection_catch"`, `"refuted"`, `"non_discriminating"`, `"inconclusive"`. |
| `proven_catch` | `boolean` | `true` if `verdict` is `"proven_catch"` or `"reproduction_catch"`; `false` otherwise. |
| `disposition` | `enum` | Fine-grained execution disposition: `"catching"`, `"head_failed_base_failed_latent"`, `"head_passed"`, `"head_uncollectable"`, `"base_uncollectable"`, or refusal status. |
| `provenance` | `object` | Execution environment and tool commit metadata (see below). |
| `sandbox` | `object` | Container and namespace isolation settings (`mode`, `backend`, `image`, `confined`, etc.). |
| `refusal` | `object` or `null` | Structured refusal details if execution was refused before or during runs. |
| `base_execution` | `object` | Execution result of candidate test on base commit revision. |
| `head_execution` | `object` | Execution result of candidate test on head commit revision. |
| `rerun_agreement` | `boolean` | Flakiness verification across head reruns. |
| `wall_clock_s` | `number` | Total execution wall clock time in seconds. |
| `provider_cost_usd` | `number` | Total LLM model provider cost incurred during verification in USD (0.0 for deterministic verifier). |
| `signature` | `object` | Cryptographic signature over receipt hash-chain (Ed25519). |

### `provenance` Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `repo_path` | `string` | Display path to repository under test (display metadata only). |
| `repo_canonical` | `string` | Normalized repository identity (e.g. `github.com/org/repo` or `local:<hash>`). |
| `base_sha` | `string` | 40-character hex commit SHA for PR base revision. |
| `head_sha` | `string` | 40-character hex commit SHA for PR head revision. |
| `test_file_name` | `string` | Basename of the verified test file. |
| `test_file_sha256` | `string` | 64-character SHA-256 digest of verified test file source. |
| `tool_commit_sha` | `string` | 40-character hex commit SHA of `jittest` tool executing the verification. |
| `tool_branch` | `string` | Branch ref of `jittest` tool executing the verification (`git rev-parse --abbrev-ref HEAD`). |
| `tool_dirty` | `boolean` | Dirty state flag of `jittest` repository (`git status --porcelain`). |
| `tool_tree_sha` | `string` | 40-character hex tree SHA of `jittest` tool. |
| `rel_path` | `string` | Relative path within monorepos (default `"."`). |

### `base_execution` and `head_execution` Objects

| Field | Type | Description |
| :--- | :--- | :--- |
| `outcome` | `enum` | Execution outcome: `"PASS"`, `"FAIL"`, `"ERROR"`, `"TIMEOUT"`, `"NOTRUN"`. |
| `failure_kind` | `enum` | Failure classification: `"assertion"`, `"error"`, `"timeout"`, `"collection"`, `"import"`, `"none"`. |
| `exit_code` | `integer` | Subprocess exit code (-1 if unexecuted). |
| `stdout_sha256` | `string` | 64-character SHA-256 digest of standard output. |
| `stderr_sha256` | `string` | 64-character SHA-256 digest of standard error. |
| `environment` | `object` | Environment resolution details. |

### `signature` Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `algorithm` | `string` | Asymmetric key algorithm, strictly `"Ed25519"`. |
| `verifying_key` | `string` | 64-character hex Ed25519 public key. Legacy receipts (v0.3.x) use `public_key`. |
| `value` | `string` | Base64-encoded Ed25519 signature over canonicalized payload string. |

## Verification & Recomputation Protocol

To verify an evidence receipt against this schema:
1. Run `jittest verify-receipt <artifact.json>`.
2. Evaluates five independent dimensions:
   - `signature_valid`: Cryptographic Ed25519 signature integrity.
   - `signer_status`: `TRUSTED` | `UNTRUSTED` | `UNVERIFIED` | `INVALID_FORMAT`.
   - `schema_status`: `VALID` | `VALID_LEGACY` | `INVALID` | `UNSUPPORTED`.
   - `provenance_status`: `MATCHED` | `MISMATCH` | `UNRESOLVABLE` | `NOT_CHECKED`.
   - `execution_trust`: `CONFINED` | `UNCONFINED` | `REFUSED` | `UNKNOWN`.
3. Validates cross-field semantic invariants (`verdict`, `outcomes`, `failure_kind`, `rerun_agreement`).
4. Optionally authenticate signer identity with `--expected-signer <key_or_fingerprint_or_allowlist>` and enforce with `--strict-signer`.
5. Optionally verify provenance consistency with `--expected-base`, `--expected-head`, `--expected-test-sha256`, and `--expected-repo`.
6. Optionally enforce execution isolation with `--require-confined`.

### CLI Exit Codes (`verify-receipt`)

| Exit Code | Condition |
| :--- | :--- |
| `0` | All requested checks passed |
| `2` | Signature invalid (payload tampered or malformed signature block) |
| `3` | Signer untrusted or unverified under `--strict-signer` (or mismatched expected signer) |
| `4` | Schema invalid or unsupported version |
| `5` | Semantic invariant violated (e.g. catch verdict on pass/pass outcomes) |
| `6` | Provenance mismatch or unresolvable reference |
| `7` | Execution not confined under `--require-confined` |
