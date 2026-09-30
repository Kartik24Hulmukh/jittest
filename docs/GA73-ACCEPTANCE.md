# GA73 acceptance: labels and all-in cost are not yet supplied

The default checkpoint is **valid but blocked**: independent human labels and
provider wallet/CI reconciliation remain `null`. No current archive is upgraded
to human ground truth or total charged spend. Original evidence is unchanged.

## Decisions

- Missing, unreadable, duplicate-key, nonfinite, malformed, or source-mismatched
  acceptance input: `NO_GO` (unless tool availability separately yields
  `NO_GO_TOOL_MISSING`).
- A valid checkpoint with either labels or cost absent: `GO_LAUNCH_NOT_GA` when
  engineering gates pass. Deleting the static #73 blocker cannot change this.
- Completed source-bound acceptance **and** no remaining static blockers **and**
  all engineering gates passing: `GO_GA`. Acceptance alone does not close issues.
- The frozen cohort rates remain conditional historical measurements, not
  universal recall or representative multi-project FPR. Other #73 requirements
  still need human issue review; this module is not an adoption or traction gate.

Run offline (repository root; no model calls, Docker or network):

```sh
PYTHONPATH=src:. python -m eval.ga73_acceptance
PYTHONPATH=src python scripts/launch_gate.py --json launch-report.json
PYTHONPATH=src python scripts/launch_gate.py --ga73-acceptance owner-manifest.json
```

An explicitly supplied missing manifest fails; omitting the option uses the
explicit blocked checkpoint whose source hashes come from the preserved baseline
manifest. The verifier rechecks original archive hashes and deterministic cohort
construction. `build_report` accepts only the validator-produced internal result type; a raw
JSON/dictionary declaration of readiness fails closed. This is an API boundary,
not a sandbox against malicious Python already running inside the process.

## Minimal manifest

Top-level keys are exactly `schema_version` (integer `1`), `sources`, `labels`,
`cost`. `sources` has `bugs` and `click`, each `{path, sha256}` matching the frozen
GA73 bug/Click archive identities. Labels and cost may each be `null`; missing
keys or a partial non-null section are invalid, not blocked. Input never supplies
`ga_ready`, headline rates or arbitrary denominators.

Every evidence reference is `{path, sha256}` with a relative repository-contained
file path (symlink escapes refused) and its actual SHA256. References are checked
without including their contents or credentials in the launch report. Use only
sanitized review/billing evidence. Do not attach tokens, provider account secrets,
unsanitized invoices or personal account identifiers.

### Independent human labels

Non-null `labels` requires:

- `reviewer_kind: "human"`, nonempty `reviewer_id`, literal-boolean
  `independent`, `blinded`, `private_custody`, and
  `labels_locked_before_unblinding`, all true.
- `attestation` reference to JSON containing those same fields, matching
  `sources`, a nonempty separate `custodian_id`, and `case_records_sha256`.
  This digest locks the full case records (including decisions, rationale,
  material and evidence references), sorted by `case_id`, JSON-encoded with
  sorted keys, compact separators, UTF-8 and `ensure_ascii=False`. List order
  is not meaningful; changing a decision or reference invalidates the lock.
- `cases`: exactly one record for every derived population and catching-candidate
  case ID. The 25 historical bugs and the full 55 Python-changing PR sampling
  frame are covered, including 15 static exclusions. All 36 mechanically catching
  assertions require review. The public template/key is not a blinded review:
  a custodian must privately remap/shuffle packets, lock completed human work,
  then map completed records back to source-bound IDs for acceptance.

Each record has `case_id`, nonempty `rationale`, and an `evidence` reference.
Population records require resolved `ground_truth: "clean" | "defect"`.
Candidate records require literal booleans `assertion_valid`,
`defect_correspondence`, `surfaced`, resolved
`change_intent: "intended" | "regression"`, and a `material` reference.
Candidate material JSON retains `case_id`, exact UTF-8 `candidate_bytes`, their
`candidate_sha256`, source archive `source_sha256`, exact `json_pointer`,
`runner: "pytest"`, `base_outcome: "pass"`, `head_outcome: "fail"`.
Candidate hashes must match archived telemetry and per-row surfaced counts must
match archived reports. Existing suppressed candidate bodies are not retained:
this check cannot be completed by labeling failure excerpts or model verdicts.

FPR is reported PRs divided by human-labeled clean PRs in the full sampling frame
(including exclusions). Product defect recall is rows with a surfaced,
human-validated regression assertion corresponding to the defect divided by
human-labeled defect rows in the attempted bug cohort (including risk skips).
Each denominator must be positive. This is not mechanical catch rate and does
not turn an unreported candidate into a product detection.

### Provider wallet and CI reconciliation

Non-null `cost` requires literal `complete: true`, `currency: "USD"`, finite
nonnegative decimal-string `provider_total_usd`, `ci_total_usd`,
`ci_allocation_usd: {bugs, click}`, plus references to `statement`,
`dispatch_inventory`, `ci_receipt`, `reconciliation_attestation`.

- `dispatches`: each actual HTTP dispatch/retry, including generator, assessor,
  timeouts and transport failures, with unique nonempty `dispatch_id`, population
  `target_case_id`, `stage: "generator" | "assessor"`,
  `transport_status: "response_received" | "timeout" | "transport_error"`,
  nonempty `provider_request_id`, `statement_line_id`, decimal-string
  `amount_usd`. Unknown debit is not zero and cannot pass.
- `statement_lines`: unique `line_id`, exact allocated `dispatch_ids`, and
  `amount_usd`. Consolidated lines may allocate multiple dispatches, but allocated
  amounts must sum exactly. No unassigned statement line or dispatch passes.
- Statement JSON: `currency: "USD"`, identical `lines`, decimal-string
  `opening_balance`, `closing_balance`, `topups`, `refunds`, `other_debits`.
  Opening + topups + refunds − closing − other debits must equal provider total.
  For EUR wallet statements retain the independently evidenced USD conversion
  and original sanitized FX/balance reconciliation in referenced materials;
  a token/list-price estimate is not a wallet statement.
- Inventory JSON: matching `sources`, identical `dispatches`, `complete: true`.
  Received-response counts must match archived model responses per evaluated
  target, and provider total cannot be below archived response-credit debits.
- CI receipt JSON: matching `sources`, `currency: "USD"`, matching `total_usd`
  and `allocation_usd`. Allocations must sum exactly to CI total.
- Owner attestation JSON: matching `sources`, `scope_complete: true`, and a
  nonempty `owner_id`. Failed/unreceived calls and all charged statement lines
  must be included. A request-count ceiling is not proof of dispatch coverage.

The module recomputes provider, CI and combined totals and cohort-specific
all-in cost per attempted target (25 bugs and 40 evaluated PRs), without blending
these populations. Current totals remain null because none of this evidence has
been supplied. No fabricated dispatch or reviewer record is checked in.

## Trust boundary and tests

Offline hashes establish artifact identity and joins, not that a person truly
worked blind or a provider statement is authentic. Independent reviewer/custodian
and owner attestations are an external human trust boundary requiring actual
review. Agent analysis, synthetic tests and model assessments are not blinded
human work, consent, adoption, wallet authority or GA certification.

`tests/test_ga73_acceptance.py` uses clearly named **synthetic** temporary test
fixtures for the completed path, never writes labels or costs into original
archives, and tests rejection paths. Default-checkpoint tests exercise the real
immutable evidence but keep all unsupplied human/all-in metrics null.
