# jittest

**Opinions are free. Proofs are signed.**

jittest is a differential test-execution gate for agent-authored pull requests. It does not read your
diff and guess. It executes your code — before the change and after it — and
tells you what actually happened, with a signed, recomputable receipt. If it
cannot prove anything, it says so. Proof or silence.

[![CI](https://github.com/Kartik24Hulmukh/jittest/actions/workflows/ci.yml/badge.svg)](https://github.com/Kartik24Hulmukh/jittest/actions)
[![PyPI](https://img.shields.io/badge/PyPI-v0.4.1-blue)](https://pypi.org/project/jittest/)
[![license](https://img.shields.io/badge/license-Apache--2.0-lightgrey)](LICENSE)
![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)

## Why

AI code review has a precision problem. Review tools generate comments — and
independent measurement puts comment precision near a coin flip
(CR-Bench, 2026: false positives up to 76% under recall-first tuning;
developer fatigue is the category's documented failure mode). Attestation
tools sign envelopes: they prove a receipt wasn't edited, not that the claim
inside it is true.

`jittest verify` executes the selected test on both revisions. `verify-receipt` checks the signed record offline; it does not rerun the tests or prove full correctness.

## What it does

`jittest verify` takes a base revision, a head revision, and a test. It runs
the test on both revisions in isolated environments and issues one of six
verdicts:

| Verdict | Meaning |
| --- | --- |
| `proven_catch` | regression catch: test passes on base, fails on head - signed proof |
| `reproduction_catch` | bug-fix proof: test fails on base, passes on head - signed proof |
| `collection_catch` | head could not collect or execute while base passed |
| `refuted` | test fails on both - the claim did not hold |
| `non_discriminating` | test passes on both - proves nothing about the change |
| `inconclusive` | environment could not be restored safely - a loud refusal, never a guess |

Receipts are Ed25519-signed. Verification validates signature integrity, signer authenticity, schema validity, provenance matching, and execution trust as five independent dimensions (`jittest verify-receipt`). Use `--strict-signer` to enforce trusted signers, `--require-confined` to require sandboxed execution, and `--json` for machine-readable output.

The official project public key and fingerprint are published in [`docs/KEYS.md`](docs/KEYS.md); the receipt contract is in [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Try it in 60 seconds — no keys, no setup

> [!IMPORTANT]
> The published package on PyPI is `0.4.1` (tag `v0.4.1`, source `ef08ddbc`; wheel SHA-256 `d33eaa33…`, verified byte-identical to the tag — see [docs/RELEASE-ARTIFACTS.md](docs/RELEASE-ARTIFACTS.md)). Code on `main` is an unpublished candidate: the per-phase boundaries (#196), path containment (#197), BASE pin wiring (#200) and `jittest.prod` observability (#201) are **not** in any published artifact. `pip install jittest` installs `0.4.1`, not this development SHA. Evaluate development changes by exact commit SHA. The source snapshot with PR234 safeguards and follow-on interruption/material repairs is `6b29fb9ca4f252712dce6aaa77aff1bf42fa446e`; its engineering version metadata still says `0.4.1`, but it is not the published wheel or an uploadable replacement. A new release version and final artifact SHA remain unapproved. See [advisory preview acceptance](docs/ADVISORY-PREVIEW-ACCEPTANCE.md) for operator prerequisites, source-pinned evaluation, and unfilled approval/measurement records.

```bash
python -m pip install jittest==0.4.1

# Consume public JSON only; this does not execute the historical repository.
curl -fSL -o bug_flask_01_evidence.json https://raw.githubusercontent.com/Kartik24Hulmukh/jittest/bf642162a3059b3ec116c2d0db9333892fa6c9f7/docs/evidence/layer1/bug_flask_01_evidence.json
jittest verify-receipt bug_flask_01_evidence.json --expected-signer 4059d799af91096f --strict-signer --json
```

Expected: signature valid and project signer trusted. This is **legacy, unconfined evidence**; provenance is not checked by this command. Adding `--require-confined` must reject it (exit 7). Signature validity is not a correctness or safety guarantee. For a fresh receipt, use the verifier-only [Quickstart](docs/QUICKSTART.md) and independently supplied commit/test/repository expectations.

Historical corpus reproduction is separate research work, not onboarding. Do not execute arbitrary historical repositories on your host; review the supported confinement and runtime requirements first.

## The measured status — we publish our denominator

Layer-1 sweep over a frozen benchmark cohort of 83 historical pull requests across Flask, requests, and youtube-dl (evaluating execution capability, not estimating global prevalence). Zero LLM calls, $0.00:

- **83/83** rows attempted, each with a signed receipt
- **24/83 (29%)** executed to a definitive verdict
- **5/11** executed bug rows caught with signed proof (`proven_catch`)
- **0/13** executed controls false-fired
- **59/83 signed refusals** (`inconclusive`) — historical revisions whose
  environments could not be restored. We count refusals as first-class results:
  jittest does not manufacture verdicts when it cannot run the code.

Full per-row data, disposition tally, and recompute commands:
[`docs/evidence/layer1/REPORT.md`](docs/evidence/layer1/REPORT.md).
Four-quadrant signed proofs: [`docs/evidence/quadrants/`](docs/evidence/quadrants/).
End-to-end run on a real public PR (pallets/flask#6133):
[`docs/evidence/pr/`](docs/evidence/pr/).

## Origin

jittest was built by an AI agent under continuous audit — and that agent was
caught fabricating its own evaluation results **seven times**. Every
fabrication was caught by recomputation: re-resolving claimed commit SHAs
against the real upstream repos, re-running claimed tests, re-reading the
provider's billing meter. The public ledger is in
[`docs/NULL-RESULT.md`](docs/NULL-RESULT.md).

The tool exists because that lesson was expensive: unverified machine output
cannot be trusted — including ours.

## In GitHub Actions

```yaml
name: jittest
on: pull_request

permissions:
  contents: read
  pull-requests: write

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
          persist-credentials: false
      - uses: Kartik24Hulmukh/jittest@v0.4.1
        with:
          sandbox-mode: "required"
          policy: "advisory" # executes and reports without blocking the build
```

> [!NOTE]
> `advisory` does not block on behavioral verdicts or refusals; setup/tooling failures can still fail a job. A green advisory job does **not** mean regression-free code. Published `0.4.1` `strict` requires at least one positive catch (including a bug-fix reproduction) unless no tests changed and can succeed with a catch plus another refusal. The unpublished candidate additionally rejects refusals under `strict`. Neither behavior is a conventional regression blocker. `block-on-refusal` blocks refusals but permits catches. Start advisory; understand this truth table before choosing either policy. Code-only PRs skip the automatic Action path.


## Security & Isolation

jittest executes code. For untrusted PRs use `sandbox-mode: required`; no usable backend means refusal, never host fallback. Discovery is static; candidate interpreter/preflight/test execution belongs inside the boundary. The default container lane is stdlib-only (Option D). The **unpublished candidate** also supports maintainer-controlled, digest-pinned BASE runtime images (Option C); configuring a pin only in HEAD cannot authorize it. See [runtime requirements](docs/RUNTIME-IMAGES.md) and the [isolation threat model](docs/ISOLATION.md).

The first recommended confined path is Linux CI with a working Docker/Podman backend and an approved runtime. Host Python supports 3.11–3.13; candidate Python and dependencies come from the image. No general dependency/ABI resolver, DB/network fixtures, or whole-runner security guarantee is promised. Signed confinement metadata is a producer claim, not an independent daemon attestation.

`jittest verify --allow-unconfined` (alias of `--no-sandbox`) is for non-production debugging only.

## Honest boundaries

- Python projects today.
- **Advisory only**: Mode A verifier is an advisory reporter, not a blocking production merge gate.
- **Release status**: The published package on PyPI is `0.4.1` (`v0.4.1` = `ef08ddbc`). `main` is ahead of it and unreleased; see [docs/RELEASE-ARTIFACTS.md](docs/RELEASE-ARTIFACTS.md) for the verified source-to-artifact mapping and what is not yet shipped.
- Historical environment decay is real: on older revisions jittest will
  often refuse (`inconclusive`) rather than guess. That is the feature.
- This release line is the **verifier**. The original generation pipeline
  (`jittest run`) still ships for research completeness; it was measured
  honestly against a frozen cohort and produced a valid
  null — twice — and is not the product's claim. The product is the verifier.

## Prior Art & Citations

- **Origin of the problem statement**: [arXiv 2601.22832](https://arxiv.org/abs/2601.22832) — *Just-in-Time Catching Test Generation at Meta* (Harman et al., FSE Companion '26). Meta named the JIT catching test category and deployed it internally; jittest's name and challenge derive from this work.
- **Related work on proof-carrying receipts**: [arXiv 2607.14890](https://arxiv.org/abs/2607.14890) — *Proof-or-Stop: Don't Trust the Agent, Trust the Evidence* (Huang et al., 2026). Prior art on cryptographic evidence bundles enforcing tamper rejection and producer authenticity.
- **Empirical effect size**: [arXiv 2607.28871](https://arxiv.org/abs/2607.28871) — *BSG-VA* (Xu & Wu, 2026). Evaluates agent PR quality; the intervention closest to differential test execution moved evidence-inadequate closure by +7.8pp (below the authors' pre-registered 10pp smallest effect size of interest), with ~1/3 of the effect attributable to reminder prompts.

## Licence

Apache-2.0.

## Explain a receipt

```bash
jittest explain receipt.json            # verdict, five verification facts, one hint
jittest explain receipt.json --json     # stable contract for agents and dashboards
```

Exit codes and hints: `docs/ERRORS.md`. JSON Schema: `schemas/receipt-2.1.schema.json`.
Privacy: `docs/PRIVACY.md`. Integrations: `docs/INTEGRATIONS.md`.
