# Premortem - JitTest GA launch (2026-09-12)

Written BEFORE launch, as if the launch already failed. Each failure mode
lists the regression that now guards against it. This document claims only
gates that were actually executed in this workspace.

## Failure mode 1: digest verification silently fell back to local image ID
Assume it happened: an attacker published a mirror tag whose .Id matched.
Guard: src/jittest/provision.py compares only authoritative RepoDigests and
refuses with digest_mismatch; tests/test_p0_gates.py
TestProvisioningContract.test_digest_mismatch_refuses_never_falls_back and
test_unpinned_or_malformed_digest_refused assert zero containers created.

## Failure mode 2: phase-2 container ran with network enabled
Assume it happened: a wheel fetched at run time from an attacker registry.
Guard: provision_in_sandbox creates phase 2 with network=none,
read-only rootfs, no-new-privileges, cap_drop ALL; the spec is asserted by
test_happy_path_two_phase_network_none.

## Failure mode 3: engine crash after phase 1 caused an unconfined host retry
Assume it happened. Guard: engine failures raise ProvisioningRefusal
(engine_failure_phase1/phase2); intermediate containers are destroyed in
finally blocks; test_engine_failure_phase2_never_retries_unconfined asserts
only phase-1 ever ran.

## Failure mode 4: evidence directory smuggled a symlink to /etc
Assume it happened. Guard: outputguard.scan_output_tree refuses symlink,
fifo, socket, block/char device, hard link, traversal, unicode NFC
collision, undeclared writes and oversized output;
TestOutputTrustBoundary covers each class.

## Failure mode 5: a receipt claimed reproducibility it never measured
Assume it happened. Guard: integrity.build_integrity_record requires an
explicit note whenever incomplete or non_reproducible is set, and
compare_runs reports field-level differences; TestReceiptIntegrity asserts.

## Failure mode 6: lock file drifted from requirements and nobody noticed
Assume it happened. Guard: readiness.check_lock_drift +
evaluate_readiness refuse on missing direct dependency, lock drift and
platform/ABI incompatible wheels; TestDeterministicReadiness asserts.

## Failure mode 7: 100 concurrent jobs leaked temp directories
Assume it happened. Guard: TestStressConcurrency runs 100 threaded
provisioning jobs with unique temp roots, asserts zero residue and
wall-clock under 120 s. Executed: passed.

## Failure mode 8: startup death by credential leak
The PAT printed in historical task context is compromised. Guard: rotate it
NOW, publish only via OIDC/Trusted Publishing (release.yml already uses
id-token), and never commit tokens or local evidence.

## Not yet guarded (honest open list)
- Live docker/podman digest E2E (no container engine in this workspace).
- macOS/Windows acceptance runs (Linux-only execution here).
- Named-maintainer SLOs, incident command and rollback rehearsal.
These remain GA blockers per the handoff promotion rule.

## Round-2 additions (same day, CI-driven)

9. **Platform-specific test pre-mortem missed Windows.** `test_symlink_fifo_hardlink_refused`
called `os.mkfifo` unconditionally; all three windows-latest legs of CI failed on
head `a403261`, blocking the merge. Guarding rule now: any OS-specific node
creation in a gate test must go through a capability probe, and the fail-closed
classification (`outputguard._is_special`) must additionally be pinned from
synthetic mode bits so the guard stays asserted where the node cannot be created.
Regression pinned in `tests/test_p0_gates.py`.

10. **"Digest verified" without RepoDigests is the spoofing hole.** Provisioning
accepted an engine whose `inspect_digest` matched the pin even when the engine
had no authoritative RepoDigests (exactly what a retagged local image produces).
`EngineAdapter.inspect_repo_digests` is now wired fail-closed: empty RepoDigests
or a missing pinned digest refuse BEFORE any container is created. Regression
pinned; live verification happens in the new `registry-live` CI job.
