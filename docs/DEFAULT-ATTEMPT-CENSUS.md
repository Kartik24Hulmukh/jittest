# Default verification attempt census

The public `jittest verify` and Action entrypoints now retain an additive invocation
census. This is **execution instrumentation**, not a labeled benchmark, human
judgment, generator replay, or proof of correctness. Generation remains separate.

## Artifact contract

- Successful signed schema 2.1 receipts add `attempt_census`; existing verdicts,
  dispositions, policy exits, and summary fields retain their meanings.
- When an output path exists, `census/<unique-run-id>/snapshot.json` and
  `journal.jsonl` are exported beside the receipt. The Action additionally exports
  its own run-level census in the same tree, covering every changed test filename,
  including deleted/unreadable files. The run-level Action census is **unsigned**;
  completed verifier receipts independently sign their per-invocation census.
- The material digest binds the full exact candidate byte digest and byte length,
  selector, BASE/HEAD pins, and supplied refs. Unavailable material/pins are `null`,
  not the digest of invented empty code. Authoritative resolved pins and the exact
  bytes used by the verifier are journaled before provisioning/execution.
- The snapshot binds the complete journal prefix with SHA-256 and record count.
  Journal records are fsynced before an atomic snapshot replacement. A concurrent
  invocation has a different directory. This is not a multi-writer database or
  power-loss-resistant filesystem attestation; a killed process may leave a newer
  journal prefix than the last snapshot.
- A phase start is not a phase outcome. `execution_observed` means a runner outcome
  was returned, **not** that all candidates executed or all phases succeeded.
  A missing file, typed refusal, exception, interruption, or still-pending entry is
  retained without converting it into a catch. Abrupt process death can leave the
  invocation `started` and candidate `pending`/`attempted`; no terminal label is
  inferred. Python interruptions record `interrupted` when unwinding is possible.
- Input/planning refusals retain the existing no-receipt CLI contract, but an
  explicit/default output path can still contain an unsigned census. `--json`
  without `--output` exports the successful signed census only in stdout; no new
  persistent filesystem location is silently created for that mode.

## Privacy and scope

Artifacts contain local selectors/paths, Git refs and hashes, dispositions,
phase observations already represented by receipts, and exception **class names**.
They do not retain candidate source bodies, raw stdout/stderr, provider payloads,
API keys, environment dumps, or human consent/judgment. Treat paths/dependency
observations as repository metadata: keep private repository artifacts private and
review artifact access/retention before sharing. Candidate hashes are not
anonymization. No historical suppressed generator body can be recovered from them.

The existing Action coarse `ENV_SETUP_FAILED` summary contract is unchanged;
typed refusal codes and phase history are additionally retained in its census/journal
and available refusal receipts. A failed refusal export never points the new census
at a same-named old receipt in a reused output directory. Prepare-time missing candidate files have no
runner execution. Neither snapshot publication nor signing imposes OS confinement,
provider reservation, concurrency capacity, cancellation SLOs, or cleanup proofs.

## Acceptance

`tests/test_default_attempt_census.py` invokes the real CLI and Action on harmless
local Git fixtures, including a regression, deletion, invalid UTF-8 refusal and
unsafe-path refusal. Supplemental interruption injection checks that a started
phase is not reported as an observed result. No provider/network calls are needed.

`scripts/check_distributable.py` rehearses the actual installed wheel's CLI and
Action outside the source checkout, validates paired pins and material/journal
hashes, and exports the receipt and both censuses under
`distributable-evidence/` beside its manifest. CI's `consumer_action_e2e` checks
actual composite-Action artifacts, downloads that job's `jittest-evidence` upload,
and compares every retrieved artifact byte digest. Local tests are not a hosted
GitHub execution claim; the download gate requires the hosted job to run.
