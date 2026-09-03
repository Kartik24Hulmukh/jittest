# jittest

**Opinions are free. Proofs are signed.**

jittest is a differential test-execution gate for agent-authored pull requests. It does not read your
diff and guess. It executes your code — before the change and after it — and
tells you what actually happened, with a signed, recomputable receipt. If it
cannot prove anything, it says so. Proof or silence.

[![CI](https://github.com/Kartik24Hulmukh/jittest/actions/workflows/ci.yml/badge.svg)](https://github.com/Kartik24Hulmukh/jittest/actions)
[![PyPI](https://img.shields.io/badge/PyPI-v0.3.4-blue)](https://pypi.org/project/jittest/)
[![license](https://img.shields.io/badge/license-Apache--2.0-lightgrey)](LICENSE)
![dependencies](https://img.shields.io/badge/dependencies-0-brightgreen)

## Why

AI code review has a precision problem. Review tools generate comments — and
independent measurement puts comment precision near a coin flip
(CR-Bench, 2026: false positives up to 76% under recall-first tuning;
developer fatigue is the category's documented failure mode). Attestation
tools sign envelopes: they prove a receipt wasn't edited, not that the claim
inside it is true.

jittest does neither. **jittest recomputes the claim.**

## What it does

`jittest verify` takes a base revision, a head revision, and a test. It runs
the test on both revisions in isolated environments and issues one of six
verdicts:

| Verdict | Meaning |
| --- | --- |
| `proven_catch` | regression catch: test passes on base, fails on head — signed proof |
| `reproduction_catch` | bug-fix proof: test fails on base, passes on head — signed proof |
| `collection_catch` | head could not collect or execute while base passed |
| `refuted` | test fails on both — the claim did not hold |
| `non_discriminating` | test passes on both — proves nothing about the change |
| `inconclusive` | environment could not be restored safely — a loud refusal, never a guess |

Receipts are Ed25519-signed. Verification checks integrity and, when you supply `--expected-signer`, authenticity against a key you chose. Without `--expected-signer` jittest reports integrity only and exits non-zero.

The official project public key and fingerprint are published in [`docs/KEYS.md`](docs/KEYS.md); the receipt contract is in [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Try it in 60 seconds — no keys, no setup

> [!IMPORTANT]
> The published package on PyPI is `0.3.4`. Code on `main` is an unpublished alpha release candidate. `pip install jittest` installs `0.3.4`, not this development SHA. Evaluate development changes by exact commit SHA.

```bash
pip install jittest

# verify one of this repo's own published receipts with official key fingerprint
curl -sLO https://raw.githubusercontent.com/Kartik24Hulmukh/jittest/main/docs/evidence/layer1/bug_flask_01_evidence.json
jittest verify-receipt bug_flask_01_evidence.json --expected-signer 4059d799af91096f
```

Then recompute the measurement behind it end to end — the sweep script clones
its three public fixture repos (flask, requests, youtube-dl) itself:

```bash
git clone https://github.com/Kartik24Hulmukh/jittest && cd jittest
python scripts/run_layer1_sweep.py
```

Don't trust. Recompute.

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
      - uses: Kartik24Hulmukh/jittest@v0.3.4
        with:
          sandbox-mode: "required"
          policy: "advisory" # executes and reports without blocking the build
```

> [!NOTE]
> The default action policy is `advisory`, which executes checks and posts PR comments/annotations but **never fails the build** (always exits 0). To use jittest as a blocking CI merge gate that fails on unproven regressions or environment refusals, explicitly specify `policy: "strict"` (requires at least 1 `proven_catch`) or `policy: "block-on-refusal"`.


## Security & Isolation

jittest executes code. Container isolation follows **Contract Option D** (Restricted support: containers execute stdlib-only candidate tests; dependency-bearing tests refuse cleanly with `isolation contract cannot import project dependencies in container mode`). Provisioning environment is scrubbed of CI secrets (`GITHUB_TOKEN`, `*_SECRET`, `*_KEY`), but runs on the runner before the sandbox wrap. For the complete isolation contract, host-provisioning threat model, and verified daemon status, see [`docs/ISOLATION.md`](docs/ISOLATION.md).

`jittest verify --allow-unconfined` (alias of `--no-sandbox`) is for non-production debugging only.

## Honest boundaries

- Python projects today.
- **Advisory only**: Mode A verifier is an advisory reporter, not a blocking production merge gate.
- **Release status**: The published package on PyPI is `0.3.4`. Version `0.3.5` on `main` is an unreleased alpha candidate.
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
