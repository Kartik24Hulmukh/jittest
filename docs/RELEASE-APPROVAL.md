# Exact-byte external release approval

## Status and authority boundary

The release workflow now **refuses publication without an explicit external
SHA-256 approval**. A file in the repository or downloaded artifact is not an
approval by itself. The independently maintained effective
`JITTEST_RELEASE_APPROVAL_SHA256` value must equal the digest of the **raw bytes**
of `dist/release-approval.json`.

**Hosted configuration is not established by source code.** The owner-authenticated
inspection supplied during this review reported the existing `pypi` environment
with `protection_rules=[]`, `deployment_branch_policy=null`, and no environment
variables. Repository variables did not include an approval digest. This means
`pypi` is currently **not protected** and this release path is currently blocked
by the missing approval input. It does not mean reviewer protection is active.
The inspection evidence is retained outside the repository in the review handoff;
no hosted configuration was changed by this implementation.

Before a release, the owner must configure and independently verify:

1. Required independent reviewers on the `pypi` environment, prevent self-review,
   and disable administrative bypass wherever supported. Reviewers must control
   both deployment approval and the approval digest, separately from tag writers.
2. Allowed deployment refs restricted to the intended version tags. Protect the
   source branch, release workflow/checker, version tags, and floating tag from
   unauthorized changes. Required checks and trusted-publishing restrictions
   are external prerequisites, not facts proven by this file.
3. Set `JITTEST_RELEASE_APPROVAL_SHA256` **only as a `pypi` environment variable**.
   **Prohibit the same variable name at repository and organization scope.**
   Audit both scopes and any inherited settings before approving. The supplied
   repository inspection did not find a collision; organization origin has not
   been observed and still needs verification.
4. Verify PyPI trusted publishing is bound to the intended repository, workflow
   and environment. This patch does not inspect or configure PyPI.

The script receives GitHub's **effective** `vars` value. GitHub's `vars` context
provides no provenance attestation showing which scope supplied that value.
The checker cannot detect an organization/repository same-name collision, verify
reviewer configuration, or distinguish an environment value from a fallback.
A correct digest alone does **not** prove independent authorization if the
external policy above is absent. A malicious tag that replaces the workflow or
checker can bypass repository-local logic unless external policy prevents it.

## What is bound and rechecked

The build runs the existing tests and exact distributable rehearsal, then creates
`release-approval.json`. Its creation is **not approval**. It binds:

- SHA-256 of raw `candidate-manifest.json`, including all its qualification/census
  fields without requiring a fixed schema for future census additions;
- exactly one wheel and one sdist, their basenames and full-byte SHA-256 digests;
- repository, commit SHA, committed source tree, full ref/tag, project version;
- triggering event, workflow ref, run ID, and **original build attempt**;
- explicit boolean `pypi`, `github_release`, and `floating_v0` effect flags.

Candidate source/version must match the checked-out execution context; candidate
working diff must use the clean-source sentinel. The tag must resolve to that
commit and match `v` plus the project version. This is a byte/context approval
boundary, not a fresh proof of confinement, model performance or truth of every
claim in the candidate manifest. The distributable/census gates own qualification.

Only tag **pushes** request publication. `workflow_dispatch`, even on a version
tag, produces an all-false plan and skips effect jobs. Only canonical final
`v0.x.y` tags request `floating_v0`; prerelease/dev/post/local tags never do.
Reviewers may explicitly disable some requested flags before hashing the raw
approval file; they cannot enable effects prohibited by event/channel. A disabled
effect fails closed at its job, rather than silently treating partial approval
as full success.

Publish, registry verification, GitHub release and floating-tag jobs download the
artifacts afresh and verify external approval plus local exact artifact inventory
and bytes before continuing. All use environment `pypi` to access the same
external approval. The original build-attempt output is propagated through the
job graph. A downstream-only rerun may retain that original attempt; rebuilding
changes the attempt and requires a new manifest and new approval. Missing upstream
outputs refuse verification, not infer a new attempt from the current job.

Strict JSON refuses duplicate keys at every depth, `NaN`, infinities, and numeric
overflow such as `1e999`. Effect flags must be actual booleans, not `1` or a string.
Manifest hashes are of raw bytes: whitespace-only edits also invalidate approval.
No approval value is automatically copied from an artifact into the `vars` input.

## Operator procedure (requires hosted policy above)

1. Review the proposed protected source/tag and qualification evidence. A dispatch
   rehearsal is nonpublishing and useful for validation, but its approval manifest
   cannot be reused for a push: event/ref/run/attempt are bound.
2. Trigger the intended tag-push build under the externally authorized process.
   The effect jobs wait for environment approval. Download the `dist` build
   artifact from the exact run and attempt; inspect both JSON manifests and all
   evidence. Independently hash the raw files and actual wheel/sdist.
3. The build's logged digest is a convenience, **not independent authority**.
   Compute `sha256sum release-approval.json` on the reviewed file. If intentionally
   narrowing flags, replace that file in the approved artifact through a controlled
   build process; changing a local review copy alone does not change the artifact
   downstream jobs will receive. A narrowed plan must be present in the artifact
   before hashing and approval.
4. Set that exact lowercase 64-hex digest in the protected `pypi` environment only,
   confirm the scope/collision policy and required-reviewer/ref settings, then
   approve the pending job. Never put the digest in a repository file as a
   substitute for this independent step.
5. Review each downstream environment gate. Changed/missing bytes or approval
   values fail before that job's effect. Registry availability/byte check still
   precedes GitHub release and floating-tag advancement. A post-publication
   failure does not retract a PyPI upload; handle that incident separately.
6. Revoke/rotate the environment digest after completion. Rebuilds/new runs require
   newly reviewed digests. Do not reuse a prior run's digest.

Repeated environment checks are intentional; they do not create a release-wide
atomic transaction. Concurrent independent releases, tag monotonicity, withdrawal
of already published bytes, and hosted configuration drift still need operator
policy. Local tests do not establish any hosted job execution result.

## Offline verification

```sh
python -m unittest tests.test_release_approval tests.test_release_dry_run \
  tests.test_release_acceptance_contract -v
```

These tests use harmless temporary Git repositories and bytes. They make no
provider requests, remote writes or production tag changes. They cover exact
approval, denial cases, context/attempt replay, raw-byte changes, strict JSON,
dispatch/channel policy and workflow ordering. Source-level workflow tests are
not evidence of hosted reviewer/ref/variable behavior.
