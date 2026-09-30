# Jittest correctness repair report

Scope: checkout `/data/jittest`, baseline `bf642162a3059b3ec116c2d0db9333892fa6c9f7`, branch `harden/jittest-v1-launch`. Read the full correctness council and relevant product strategy, risk and council resolution sections. No commits, pushes, paid APIs, real credential/key files, release publication, original cohort/evidence changes or proc/transport changes.

## Frozen reproductions

- `/data/correctness-baseline.txt`: 22 focused cases; **20 failed, 2 passed** before source edits. Real Git commits/worktrees, real dependency-free runner, canonical signatures with public deterministic fixture seed; provisioning and API/comment boundaries intercepted. Reproduced non-assertion proof, insufficient reruns, malformed signed verdicts, synthetic merge-vs-event pair, missing ref green skip and path-vs-GitHub-identity lookup.
- `/data/correctness-cli-baseline.txt`: **both subprocess entrypoints failed** against the frozen baseline source. Composite-like empty `JITTEST_PR_NUMBER` and a real synthetic merge checkout did not produce the intended event-pair evidence.
- `/data/correctness-body-import-baseline.txt`: runtime `ModuleNotFoundError` reproduced a further producer/consumer inconsistency (inconclusive plus collection classification rejected by receipt semantics).
- `/data/correctness-sandbox-refusal-baseline.txt`: signed, genuinely NOTRUN required/none refusal independently rejected by baseline semantics.

## Repairs and root causes

1. **Action exact pair / no green comparison failure.** Empty PR number is absent, inferred from event/ref. Read and validate event base/head SHA; REST fallback uses canonical owner/repo, never a filesystem path. Missing/unresolved PR pair cannot fall back to checkout HEAD/merge. Resolve both exact commit objects locally before diff; failed diff emits a truthful refusal and unknown denominator. Strict and block-on-refusal fail; advisory warns. No automatic network fetch or confinement downgrade.
2. **Independent consumer acceptance.** Action checks actual signed schema-2.1 evidence, pair, candidate source hash and canonical repository identity before counting a producer boolean. Invalid receipts retain the producer artifact, report `refused_invalid_receipt`, and contribute zero catches. Strict also fails if other tests refused. This is signature integrity/schema/provenance acceptance, NOT trusted-signer governance or universal isolation proof.
3. **Producer classifications.** Only assertions can establish behavioral regression/reproduction proof. Ordinary runtime exceptions are non-proof inconclusive results; runtime import failures are non-behavioral collection results, blocked as refusals by the Action. Timeout/NOTRUN are not mislabeled collection proof. Existing receipt assertion requirements were not weakened.
4. **Rerun contract.** Public verifier refuses non-integer/bool and values below two before execution; honors requested head execution count. Agreement includes outcome AND failure classification. Modern behavioral proof requires recorded distinct head/rerun assertion executions matching head revision and candidate hash. Absence, duplication, changed failure classification, wrong revision/hash and single head record cannot establish proof. Legacy schema compatibility is retained, but the Action requires schema 2.1.
5. **Malformed signed inputs.** Guard verdict enum membership against arrays/objects for both legacy and 2.1; legacy hash matching is type-safe. Structured invalid results replace TypeError; no indiscriminate catch of cancellation/process-control exceptions introduced.
6. **Installed-wheel provenance.** Verify uses embedded `_build_provenance.json` (parent-owned build hook) before source checkout fallback. Require exact 40-hex source SHA and 64-hex working-diff hash. Missing build identity only falls back in a genuine tool source checkout with matching Git root, never site-packages or arbitrary cwd. Embed build metadata in signed provenance; dirty builds are not falsely labeled clean. Bad/missing installed identity refuses honestly.
7. **Operational reporting.** Every Action return path writes bounded best-effort `GITHUB_STEP_SUMMARY`, even if comment publication is denied; summaries never determine policy. Required/no-backend standalone CLI carries an observed plan refusal into a signed receipt, with both executions NOTRUN. Required/none receipt semantics permit only a genuine non-executed inconclusive refusal; any claimed execution remains invalid.

## Coverage and compatibility

New `tests/test_correctness_contracts.py` uses public deterministic seed only and temporary repositories/output. Real subprocess `jittest.action` and `jittest.cli action` execute real Git diff/worktrees, mini runner, signing, independent acceptance and policy; only provisioning/private-key/API-comment boundaries are replaced. There is optional fresh-wheel offline installation coverage via `JITTEST_TEST_WHEEL=<wheel>` (`pip --no-index --no-deps --target` temporary directory).

Existing `test_action.py` policy/sandbox unit fixtures now explicitly mock resolution/receipt acceptance and isolate all output in temporary directories; these are not claimed as integration evidence. Strict valid receipt fixture now supplies actual synthetic head/rerun metadata. Only three synthetic negative fixtures were minimally strengthened and re-signed with public fixture seed to retain their original isolated signer/provenance CLI exit assertions; original signed launch/cohort evidence is untouched.

Last completed pre-final-expansion focused run: **110 passed, 1 skipped** (wheel path not provided), 36.77s. Entrypoint/identity/summary subset: **13 passed**, 1.53s. Final expanded results and installed-wheel acceptance are recorded below/as separate parent-run logs. Lint and mypy run against all three modified source modules.

## Council cross-examination / limits

The council's five bounded findings are addressed without relabeling exceptions as assertions, loosening behavioral receipt requirements, treating failed diff as test-free, accepting a nonexistent rerun or trusting producer booleans. New refusal compatibility permits no successful execution. Modern historical catches lacking observed rerun metadata will no longer pass the strengthened proof semantics; historical launch evidence was not rewritten to manufacture it. These local fixtures are bounded correctness evidence, not hosted GitHub/fork runner tests, paid-provider soak, real Docker deployments, cross-platform evidence, trusted signer enrollment, GA certification, zero-FPR or SLO guarantees. Maintain limited advisory/pilot positioning.

## Final measured lane checks

- `/data/correctness-final-tests.txt`: **168 passed, 1 skipped**, 43.81s, covering correctness contracts, Action unit fixtures, strict receipt/verify/signing tests and all `test_p0*.py`. The one skip is explicitly optional fresh-wheel installation coverage when `JITTEST_TEST_WHEEL` is unset.
- `/data/correctness-negative-corpus.txt`: **17 passed**, 0.25s, including unchanged signer/provenance CLI exit expectations.
- Ruff: all owned source/test files passed. Mypy: **no issues in 3 source files**.
- Source frozen after these changes. Parent owns full-suite, fresh exact-artifact wheel/sdist and genuine-CI acceptance. Do not infer those results from this lane.
