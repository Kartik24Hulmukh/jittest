# Independent production/launch review — Jittest

**Review date:** 2026-09-30. **Baseline:** `bf642162a3059b3ec116c2d0db9333892fa6c9f7`. **Disposition: bounded verifier preview only; NO GA or general untrusted-code safety certification.** Final candidate acceptance is conditional on the stable shipped-artifact checks below, not on source help commands or synthetic load alone.

## Scope / independence

Initial read-only audit of packaging, onboarding, Action/release workflows, confinement boundary and correctness contracts. Parent subsequently authorized edits only to `README.md`, `docs/QUICKSTART.md`, `docs/RUNTIME-IMAGES.md`, `docs/ISOLATION.md`, `docs/KEYS.md`; no source/workflow/test files owned by other agents were edited. All private reviewer harnesses, builds and own harmless Git fixtures are in `/data/launch-audit/`. No push, commit, publication, outreach, paid calls, historical corpus host execution, operational credentials or further subagents. Ephemeral fixture signing material is not a project signing identity.

Research reviewed: council-launch/correctness/evaluation, strategy final and both Astra verdicts, master instructions/handover, prior hardening and launch blueprints, repository inventory and zipped founder/phase strategy context. Older prompts are historical scope/evidence, not authority to publish or run their scripts. Market/model claims conflict (Astra verified vs unverified); not needed for technical acceptance and not independently verified here. No competitor/funding facts or revenue forecasts inferred. All archive members inventoried; no archived helper executed. Screen recording: 30.27-second H.264 1920×1080, frames extracted; OCR unavailable (`tesseract` binary absent), therefore not treated as technical evidence. Embedded credentials were not used or reproduced.

## 1. Concrete baseline P0: exact installed wheel cannot consume its own fresh receipt

Built both artifacts from an immutable `git archive` of baseline, outside checkout. Wheel installed `--no-deps` into a clean dedicated venv. **53 Python package modules match baseline source byte-for-byte**. Executed only our own tiny `double(2)` Git fixture: BASE returns 4, HEAD returns 6, same selected test asserts 4.

- Baseline `verify --sandbox-mode off --reruns 1` returned 0 / `proven_catch` and signed an actual unconfined receipt.
- Independent consumer with expected public signer, full base/head and test hash returned **4 / SCHEMA_INVALID**: `provenance.tool_commit_sha` was empty because site-packages is not a Git checkout. Signature valid, signer trusted, requested provenance matched, semantic check passed. **A source checkout passing tests cannot establish clean-installed success.**
- `required` with no backend exited 2 before producing a CLI receipt; no backend means no execution, not a fresh confined success.
- Existing immutable public receipt consumer: authentic expected signer 0; require-confined 7; unspecified signer 0/UNVERIFIED; strict unspecified signer 3; wrong signer 3; altered payload 2.

Evidence: `/data/launch-audit/build.log`, `rehearsal.json`, `unconfined-consumer.stdout`, `required-refusal.stderr`, individual consumer logs. This baseline was independently frozen before parent/correctness modifications. Parent is addressing P0 with build-time archived provenance and a fresh installed-wheel fixture gate; acceptance of that fix must use the final artifact, not a patched source interpreter.

## 2. Corrections made within authorized documentation ownership

- Canonical verifier-only entry path: exact published package pin, immutable JSON receipt download using fail-on-HTTP-error curl, explicit legacy/unconfined/no-provenance scope and negative controls. Removed historical corpus host execution from activation.
- Removed generator API/model setup from Quickstart activation; retained legacy generator as optional research, not verifier telemetry.
- Removed nonexistent Action `runtime-image` input and obsolete `v0.3.5` example. BASE pin/operator authority, HEAD tamper limitations and placeholder warning now precede examples. No image catalog or pretend runnable pin supplied.
- Corrected runtime example to writable disposable worktree, actual 512 MiB executable tmpfs and nonroot host identity/root fallback; corrected inventory/readiness prose to metadata enumeration and limited requirements support, not a universal import/ABI resolver.
- Corrected no-signer default vs strict exit codes; project public signer is not the signer for arbitrary partner receipts.
- Separated signed confinement metadata from real daemon attestation and test completeness. Kept published 0.4.1/source mapping unchanged. Documented published vs candidate strict-policy differences when correctness changes began rejecting refusals.

Independent documentation Action-input scan: **no unsupported keys** in README/Quickstart/runtime YAML examples (`docs-contract.json`). Release mapping/local Action/dry-run contracts: **5 passed** (`docs-release-contract-tests.log`). No benchmark/adoption/value claim added. A fully resolved fresh confined example remains a release gate, not fabricated onboarding.

## 3. Cross-examination of correctness/source changes

Observed useful changes: validated PR event pair/exact local commit objects, canonical owner/repo lookup instead of local path, explicit comparison failure instead of zero-test skip, assertion-class behavioral catches, >=2 head executions, type-safe malformed verdict validation, and independent Action receipt semantic/provenance verification.

Initial focused rerun during active editing surfaced four failures (blank PR event pair plus real Action/CLI entrypoint x2; empty provenance SHA classification) and was reported immediately. It is not final stable-candidate evidence. Log: `/data/launch-audit/cross-examination-tests.log`.

Residual interpretation limits even after a passing regression suite: Action's consumer check is a separate verification operation, but runs in the same trusted process and uses the producer's in-memory receipt; it is not an external trust anchor or independently rerun execution. Without a protected externally supplied signer expectation, it is not release signer governance. Generated unsigned comparison-refusal JSON is diagnostic, not a signed proof. Missing artifacts must remain visible as errors/refusals.

## 4. Release/workflow review

Baseline upload omitted `always()`; strict failure could hide existing evidence. Floating v0 advanced after build even when publication failed. Release suite installed only pytest/timeouts instead of needed dev/optional tests, and the release did not rehearse the shipped wheel. Parent-owned corrections observed: always artifact upload; fuller test dependencies; build→publish→verify actual PyPI bytes→GitHub release→floating tag; immutable-built-artifact manifest; package byte comparison and clean install gates. Dispatch remains build/test-only; no side effect was exercised here.

Cross-examination requested:
1. Preserve only wheel/sdist in the publisher input directory; manifest JSON is evidence, not a Python distribution.
2. Rebuild the sdist into a wheel, checking complete runtime source, build provenance JSON, METADATA and entry points. `*.py` comparison/help alone misses runtime-critical JSON and an unusable fresh receipt.
3. Consumer roundtrip of real own harmless fixture in installed wheel outside any Git source checkout; full independent input expectations; signer/tamper/head/confinement negatives; fail closed if tool identity is missing.
4. Record dirty/uncommitted candidate honestly: `git diff HEAD` omits untracked files. Current HEAD alone cannot identify these edits. Final release must commit reviewed bytes; archived SHA is source metadata, not another proof of correctness.
5. Keep hosted dry-run/job-skip verification and protected signer/publication permissions as unperformed operational gates. The parent subsequently pinned `pypa/gh-action-pypi-publish` to immutable `dc37677b2e1c63e2034f94d8a5b11f265b73ba33`; the former mutable-pin concern is addressed.

## 5. Actual confinement boundary — what is and is not proved

This sandbox has **no Docker, Podman or bubblewrap binaries**. We did not manufacture Docker evidence with a fake engine, or execute third-party corpus code unconfined. No fresh real-daemon probe, candidate socket/host-file/key isolation canary, dependency-bearing paired execution or daemon cleanup proof was possible here. Retained old daemon/cohort JSON can support its own recorded revision only, not the current modified distributable.

Static controls are meaningful: required refusal; BASE image authority; static discovery; image inventory without candidate mount/network; network-none, readonly root/package, capabilities dropped, nonroot candidate, resource flags, unique container names, host signing. Limits: containers share the kernel, checkout/tmp are writable, read-only system/package/venv binds can still disclose files placed there; worktree `.git`/mounted paths need a real canary check. Stock Option-D image is a mutable default image, not the Option-C digest-pinned lane. Bubblewrap is not a VM. Candidate tests cannot establish their own isolation by self-reporting `confined` in a valid signature.

**Remaining confined acceptance:** approved image actual digest and inventory; BASE pin cannot be changed by HEAD; actual candidate cannot read a synthetic host sentinel/signing sentinel or egress; paired outputs independently consumed with full expectations; cleanup on timeout/cancel; no host provisioning/candidate execution. Use synthetic sentinels, not secrets. Repeat on the exact final release bytes and GitHub runner, with any missing backend **NOT_RUN**.

## 6. Premortem: race / starvation / drift, and two worst risks

| Risk | Evidence / limit | Narrow countermeasure / stop trigger |
|---|---|---|
| Admission starvation | Own harmless subprocess probe queued behind four sleepers: child timeout 0.05 s, observed end-to-end 0.5734 s. `run_bounded` intentionally starts timeout after spawn; admission semaphore has no timed acquire. This is documented API semantics, not an extra proc-fix demand. | Supervisor must bound whole-job/admission budget and report queue latency, limits and saturation. Synthetic high worker counts are not a fairness/SLO guarantee. Do not promise per-request end-to-end timeout. |
| Shared-output/cache race | Atomic JSON replacement prevents torn files, not last-writer-wins output collisions. Same output path/run directories and shared host venv cache can race under concurrent users; no real shared deployment rehearsal here. | Distinct run/attempt output directories, immutable receipt identity expectations, isolated runner/cache ownership. Reproduce an observed failure before another hardening cycle; do not claim generic multi-tenant readiness. |
| Drift | Installed-wheel provenance P0 demonstrated; source HEAD, published 0.4.1, candidate behavior and old runtime docs diverged. Registry/Action tags and HEAD runtime changes add independent drift paths. | Exact artifact hashes + rebuilt-sdist equivalence + clean-wheel receipts; protected publish chain; BASE-only pin; candidate/release labels. A byte/signature/identity mismatch is a stop, not a warning. |
| **Worst #1: runner compromise or sensitive-file disclosure** | Actual confinement untested here; environment allowlist is not filesystem confidentiality; containers share kernel. | Required isolation on disposable least-privilege trusted runners; secrets outside all binds; actual hostile-canary gates before offering untrusted execution. Stop execution path for any leak/host-execution evidence, no `off` fallback. |
| **Worst #2: false mechanical assurance** | Baseline source incorrectly compared merge commits, collapsed diff failure into skip, emitted self-invalid/single-run catches; installed wheel emitted unusable tool provenance. Green advisory/valid signature may be mistaken for safety. | Separate evidence validity, behavioral verdict, policy and missing coverage; independently supplied signer/base/head/test/repo; known negatives; no GA or zero-FPR claims. Stop if stale/tampered/semantically contradictory evidence passes requested checks. |

Demand/retention/pricing remain untested. Comprehension and real repeated use are separate gates: two consenting owners, advisory, named supported runtime shape, all eligible opportunities/skips/refusals/errors retained, independently checked receipts and a documented decision change. No outreach, user onboarding study or external pilot performed; do not treat own seeded fixtures/100-worker tests as customer value.

## Release decision

Proceed only with corrected offline receipt-consumer/preview materials and gated candidate preparation. A fresh confined supported fixture, stable installed-wheel acceptance, hosted release dry-run, protected signer/publication governance and actual owner usability/repetition remain distinct checks. Do not call this GA, claim whole-code correctness, merge safety, model availability or commercial validation. One narrowed preview is preferable to an image fleet/platform rewrite; no new API or broad strategy program is required by this review.

## Independent frozen-candidate cross-examination (first READY snapshot)

Snapshot: `/data/launch-audit/final-snapshot`, exact files hashed in `final-snapshot-hashes.json`. Parent/correctness READY snapshot was built independently into `final-dist`, not the parent's output directory.

- Build and clean installation succeeded; installed provenance now supplies baseline source SHA and recorded dirty-diff identity, schema valid. **Initial script gate still failed exit 6:** it passed filesystem path as `--expected-repo` although receipts require canonical repo identity. Actual receipt was `local:<hash>`; canonical matching honestly returned UNRESOLVABLE. Action used the same wrong expectation, which would reject genuine real output. Reported immediately; parent/correctness subsequently changed Action to externally resolved canonical identity and gate to an offline fake remote with independently known identity.
- Public deterministic test seed's independently known public key is `03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8`; gate should assert that, not bootstrap expected signer from receipt.
- Focused frozen tests initially had 4 failures: new body-import fixture produced semantically invalid inconclusive evidence, and 3 explanation fixtures lacked newly required proof phases. These are not acceptable passing tests; corrective follow-up pending.
- Independently extracted the **actual sdist** and rebuilt it into a wheel, with no Git directory. Full archive entry sets match; **57 runtime/provenance/metadata files match byte-for-byte**, including Python package, `_build_provenance.json`, METADATA, WHEEL and entry points. `sdist-rebuild-comparison.json` and `sdist-rebuild.log`. This goes beyond the committed script's static sdist comparison and proves this snapshot can rebuild, not every future artifact.
- Offline compatibility inventory: same 152 signed public artifacts under baseline/current consumer, 147 accepted, 5 rejected, no crashes and **0 acceptance drift** (`receipt-acceptance-diff.json`). No historical producer was executed.
- Actual published PyPI 0.4.1 wheel downloaded; SHA-256 exactly matches retained mapping `d33eaa33cc24d0be2dd9dad5975ca4d3c6e3fb8640f008cea6988e7b6a8b6b95`. Installed outside source checkout: documented sample authenticity and explanation both exit 0. This is actual published-byte consumer rehearsal, not a candidate-build substitution.

### Corrected second frozen snapshot — artifact and Action acceptance

`final2-snapshot-hashes.json` identifies the corrected snapshot. Independent build plus the upgraded exact-distributable script **passed**. Wheel SHA-256 `a584f5898ce9180654d74ce88f1b7fe9cf235c18bac7e80b726325b5be354726`; sdist `9a072ba0998523fee1a561d2eca7581d96f8cf5412c1bc8cac1fc9806a9f8c36`. These are **unpublished dirty-candidate** hashes, not the published wheel; source metadata bf64216 + diff hash `563600ae8c88f837aa2c28dc5c38e28e4b2094119a90b3bbcf713a57bb56c776`. Any later test/source edit or committed release requires a new manifest.

- Fresh actual installed CLI assertion-regression receipt roundtrips with independently known deterministic public signer and externally supplied full base/head/test/canonical repo. Wrong signer 3, wrong head 6, tampered payload 2, requested confinement on unconfined execution 7. Gate no longer invents repo identity from a filesystem path or signer trust from the receipt.
- The corrected sdist was **again actually rebuilt** without a Git checkout: 57 runtime/provenance/metadata files identical; archive entry sets equal (`final2-sdist-rebuild-comparison.json`).
- **Actual installed Action entrypoint, not a mocked producer:** own harmless changed-test fixture, trusted push context explicitly off, strict exit 0 with signed catch; separate CLI consumer with full external expectations exits 0; step summary present despite no comment credentials. Fork event with explicit off is upgraded to required; no backend gives strict exit 1, signed NOTRUN refusal independently accepted (consumer 0 / REFUSED), and step summary present. No GitHub network/comment success claimed. `actual-action-rehearsal.json`.
- Source frozen focused/negative/explanation/release contracts: **148 collected, 141 passed, 3 failed, 4 skipped**, exact XML. Remaining 3 are existing `test_cli_explain.py` positive fixtures imported from `_minimal_receipt` without newly required recorded head rerun phases. Parent notified to repair the valid fixture without weakening proof invariants, and rerun the complete suite. Thus artifact/Action gate success does not justify asserting the whole suite is green.

**Remaining acceptance blocker:** three existing explanation fixture regressions until repaired and independently rerun. Separate real-daemon, hosted workflow, protected publication/signer, and customer-value gates remain NOT_RUN regardless of local fixture repair.
