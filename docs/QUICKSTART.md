# Quickstart

Verifier-only onboarding. No model API key or paid call is required.

## 1. Install

```bash
python -m pip install jittest==0.4.1
```

No runtime package dependencies are pulled in. Offline receipt consumption needs Python 3.11+; paired execution additionally needs Git and a usable isolation/runtime environment.

> The current public package and immutable Action tag are `0.4.1` (source
> `ef08ddbc`; see `RELEASE-ARTIFACTS.md`). The source on `main` is a release
> candidate until its release gates pass. Evaluate
> an unreleased candidate only by an exact commit SHA—never by mutable `main` or
> a floating major tag.

## 2. Verify a public receipt offline

No model key, provider account, candidate execution or paid call is needed:

```bash
curl -fSL -o bug_flask_01_evidence.json https://raw.githubusercontent.com/Kartik24Hulmukh/jittest/bf642162a3059b3ec116c2d0db9333892fa6c9f7/docs/evidence/layer1/bug_flask_01_evidence.json
jittest verify-receipt bug_flask_01_evidence.json --expected-signer 4059d799af91096f --strict-signer --json
jittest explain bug_flask_01_evidence.json --expected-signer 4059d799af91096f --strict-signer
```

Expected: exit 0, valid signature, trusted project signer. This public sample is **legacy and unconfined**, with provenance unchecked. It demonstrates offline receipt consumption, not fresh confined execution or proof of full correctness. Adding `--require-confined` must return exit 7. A changed payload must return 2; a wrong expected signer must return 3.

## 3. Run a selected test on base and head

For the inspected repaired source baseline, use **`0ebba4770af4cb90d95eb752175645288b9dd1c9`**, not mutable `main`; the published `0.4.1` lacks the later boundaries and BASE runtime wiring listed in `RELEASE-ARTIFACTS.md`. The host package supports Python 3.11–3.13. Linux CI with a working Docker/Podman backend is the recommended first confined execution environment; the approved runtime supplies the candidate Python and dependencies.

Install this source snapshot in a separate environment, not over the published offline-consumer environment:

```bash
python -m pip install git+https://github.com/Kartik24Hulmukh/jittest@0ebba4770af4cb90d95eb752175645288b9dd1c9
```

This is unreleased engineering source whose package metadata still says `0.4.1`, not a replacement upload for published `0.4.1`. It includes the PR232 installation/provenance repairs and PR234 GA evidence acceptance, exact-byte release approval, and default CLI/Action attempt census. This exact snapshot passed [post-merge CI](https://github.com/Kartik24Hulmukh/jittest/actions/runs/36782837751). This is engineering qualification, not independent catch/FPR, all-in cost, or GA acceptance. A future uploadable candidate still needs a new approved version, full SHA, and exact artifact acceptance. For a candidate Action evaluation, pin `uses: Kartik24Hulmukh/jittest@0ebba4770af4cb90d95eb752175645288b9dd1c9` instead of the published `v0.4.1` example below. Do not switch that example silently or treat a source pin as publication approval. See [ADVISORY-PREVIEW-ACCEPTANCE.md](ADVISORY-PREVIEW-ACCEPTANCE.md) before execution.

Before running untrusted code, require isolation and review [ISOLATION.md](ISOLATION.md). For dependency-bearing projects the candidate needs a trusted, digest-pinned runtime selected from the **BASE** configuration or a deliberate operator override; see [RUNTIME-IMAGES.md](RUNTIME-IMAGES.md). No published general-purpose runtime catalog is provided. DB/network-dependent fixtures and broad packaging/ABI resolution are not supported claims.

The following is a command **outline**, not a runnable fixture or image pin. Replace every uppercase value with independently obtained repository values. Use the actual maintainer's public signer expectation, not the project's official signer for your locally signed output. Never export the private signing key.

```text
jittest verify --repo REPO --base FULL_BASE_SHA --head FULL_HEAD_SHA --test TEST_FILE
  --sandbox-mode required --output receipt.json
jittest verify-receipt receipt.json --expected-signer TRUSTED_PUBLIC_KEY --strict-signer
  --expected-base FULL_BASE_SHA --expected-head FULL_HEAD_SHA
  --expected-test-sha256 TEST_SHA256 --expected-repo REPO_ID --require-confined --json
jittest explain receipt.json --expected-signer TRUSTED_PUBLIC_KEY --strict-signer --require-confined
```

`verify`'s behavioral exit and `verify-receipt`'s evidence-check exit answer different questions. Preserve and explain any artifact even when execution refuses or finds no distinguishing behavior. `--require-confined` checks signed execution metadata; it does not independently inspect a daemon or rerun tests. Missing runtime/backend support is an honest refusal, not a reason to use `--no-sandbox` for an untrusted PR.

## 4. Add the verifier to CI

Start in advisory mode. This collects signed receipts without claiming that the
workflow is already a production merge gate.

```yaml
name: jittest
on: pull_request
permissions:
  contents: read
  pull-requests: write
jobs:
  catching-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: Kartik24Hulmukh/jittest@v0.4.1
        with:
          sandbox-mode: "required"
          policy: "advisory"
          budget: "1.00"
          output-dir: "jittest-evidence"
```

`fetch-depth: 0` matters because the verifier needs both commits. Advisory mode
reports evidence without blocking on verdicts/refusals; setup errors can still fail.
Only changed Python test files are automatically selected; code-only PRs skip.
Published `0.4.1` `strict` requires a positive catch (or skips if no tests changed);
the unpublished candidate additionally rejects refusals under `strict`.
`block-on-refusal` blocks refusals but permits catches. Neither is a conventional
block-on-regression policy. Measure behavior before selecting either.

For fork pull requests, GitHub normally gives `pull_request` workflows a
read-only token and withholds ordinary secrets. Treat PR comments as best effort;
use uploaded evidence and any emitted job summary rather than depending on comments. Do not switch to
`pull_request_target` and execute an untrusted checkout just to obtain write
permissions.

## Optional: legacy generator research

`jittest doctor`, `run --dry-run`, `stats` and `outcome` describe the separate generator/ledger workflow, not verifier activation or evidence acceptance. `run` can call a paid model; it is not needed here. Do not interpret generator telemetry as retained verifier use. A dry run is not a proof of confinement. See the CLI help before opting into this research workflow.

## Uninstall cleanly

```bash
rm -rf .jittest/      # ledger and response cache, both local
pip uninstall jittest
```

Receipt consumption is offline. The verifier can access GitHub or a container registry when requested; the optional generator makes model calls. There is no default phone-home. Receipts can include repository identity, paths and runtime references; review/redact them before sharing.
