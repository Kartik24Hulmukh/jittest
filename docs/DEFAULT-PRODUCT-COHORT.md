# Prospective default-product replay

This is a separate technical evaluation, not replacement evidence for the historical GA acceptance study. The nine rows in `eval/default_product_cohort.json` were declared before this replay's outcomes: the first two bug-tagged rows and first control-tagged row for Flask, Click and Rich in the original Layer1B ordering. This is a small, deliberately scoped selection, not a representative random sample. The Click style case was already used in an earlier replay, so this cohort is not claimed to be entirely held out. Upstream commit/diff tags are not independent blinded human labels.

## Execution

Dispatch `default-cohort` on the exact reviewed source commit. The workflow builds and installs that commit's dependency-free Jittest wheel, creates a maintainer-controlled runtime from a resolved official Python image and fixed dependency wheels, and uses an ephemeral loopback registry solely to establish the runtime's authoritative registry digest. It does not publish a product or image to an external registry.

Public repositories are cloned as inert Git data; candidate packages are not installed or executed on the host. The runner stages each exact regular Git blob, preserves its source bundle and hashes, then invokes the installed public `python -m jittest verify` CLI with `--sandbox-mode required`. It does not generate tests or call a model. Internal model modules can still be imported by the CLI; this is not a claim of no model imports.

All nine selected rows remain in the census. Missing material, sandbox refusals, errors and invalid receipts remain visible. Do not substitute a row, edit a candidate, relax confinement, or overwrite an unsuccessful output directory to improve the result. Runtime failures require a separate documented repair and attempt. Preserve earlier artifacts.

The public outcome-bearing staging archive is unblinded; it is not a completed human review packet. A separate custodian must prepare any genuinely blinded reviewer materials.

Each produced receipt is independently consumed with expected repository, revisions, material hash and pre-established signer, plus required confinement. The private signing key is temporary and is not an exported artifact. The artifact inventory retains raw candidate bodies, source bundles, commands, stdout/stderr, census sidecars, receipt-consumption checks, image/dependency provenance and failure evidence.

## What this does not establish

Mechanical dispositions are not human recall or false-positive rate. An agent review, public commit subject, synthetic fixture or signed receipt cannot substitute for independently blinded review of assertion validity and bug relevance. A workflow timing receipt is not a currency-qualified invoice. No model dispatch on this verifier path does not prove the historical generation study's wallet reconciliation or total USD per PR.

Keep human labels, recall, false-positive rate and qualified monetary totals unavailable until the required independent evidence exists. A separate owner/custodian decision is needed before this prospective cohort can enter a new acceptance binding; it must not silently replace the frozen historical cohort. Release approval, repository protections, real pilots and adoption remain separate requirements.
