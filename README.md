# jittest

**Opinions are free. Proofs are signed.**

jittest is the verification layer for AI-written code. It does not read your
diff and guess. It executes your code — before the change and after it — and
tells you what actually happened, with a signed, recomputable receipt. If it
cannot prove anything, it says so. Proof or silence.

[![CI](https://github.com/Kartik24Hulmukh/jittest/actions/workflows/ci.yml/badge.svg)](https://github.com/Kartik24Hulmukh/jittest/actions)
[![PyPI](https://img.shields.io/badge/PyPI-v0.3.2-blue)](https://pypi.org/project/jittest/)
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
the test on both revisions in isolated environments and issues one of four
verdicts:

| Verdict | Meaning |
| --- | --- |
| `proven_catch` | test passes on base, fails on head — it discriminates; signed proof |
| `refuted` | test fails on both — the claim did not hold |
| `non_discriminating` | test passes on both — proves nothing about the change |
| `inconclusive` | environment could not be built — a loud, signed refusal, never a guess |

Every run emits an Ed25519-signed receipt (schema 2.0) with the exact SHAs,
environment, output hashes, and wall-clock. The public key is in
[`docs/KEYS.md`](docs/KEYS.md); the receipt contract is in
[`docs/SCHEMA.md`](docs/SCHEMA.md).

## Try it in 60 seconds — no keys, no setup

```bash
pip install jittest

# verify one of this repo's own published receipts, fully offline
curl -sLO https://raw.githubusercontent.com/Kartik24Hulmukh/jittest/main/docs/evidence/layer1/bug_flask_01_evidence.json
jittest verify-receipt bug_flask_01_evidence.json
```

Then recompute the measurement behind it end to end — the sweep script clones
its three public fixture repos (flask, requests, youtube-dl) itself:

```bash
git clone https://github.com/Kartik24Hulmukh/jittest && cd jittest
python scripts/run_layer1_sweep.py
```

Don't trust. Recompute.

## The measured status — we publish our denominator

Layer-1 verdict-accuracy sweep over a frozen, human-adjudicated 83-row cohort
of real Flask / requests / youtube-dl history. Zero LLM calls, $0.00:

- **83/83** rows attempted, each with a signed receipt
- **24/83 (29%)** executed to a definitive verdict
- **5/11** executed bug rows caught with signed proof (`proven_catch`)
- **0/13** executed controls false-fired
- **59/83 signed refusals** (`inconclusive`) — decade-old revisions whose
  environments no longer build. We count refusals as first-class results:
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

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: Kartik24Hulmukh/jittest@v0   # or pin @v0.3.2
        with:
          sandbox-mode: "auto"
```

If jittest proves nothing, it posts nothing. Silence is the default and it is
a feature. See [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Security

jittest executes code. Outside-collaborator PRs run sandboxed by default
(docker / podman / bwrap; `--network none` family of restrictions — see
[`SECURITY.md`](SECURITY.md)). Never run untrusted code unsandboxed.

## Honest boundaries

- Python projects today.
- Historical environment decay is real: on very old revisions jittest will
  often refuse (`inconclusive`) rather than guess. That is the feature.
- This release line is the **verifier**. The original generation pipeline
  (`jittest run`) still ships for research completeness; it was measured
  honestly against a frozen, human-adjudicated cohort and produced a valid
  null — twice — and is not the product's claim. The product is the verifier.

## Citing

Method: [arXiv 2601.22832](https://arxiv.org/abs/2601.22832) (Meta's JIT
catching-test paper). Independent validation of the proof-or-silence doctrine:
[arXiv 2607.14890](https://arxiv.org/abs/2607.14890). See `CITATION.cff`.

## Licence

Apache-2.0.
