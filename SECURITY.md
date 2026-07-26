# Security policy

## The honest threat model

**jittest executes code written by a language model.** That is unavoidable: the
differential oracle only works by running candidate tests. Please read this
before running it anywhere that is not disposable.

### v0.1 isolation: weak by design, adequate in CI

| Control | Present |
|---|---|
| Ephemeral git worktree per candidate | yes |
| Hard subprocess timeout | yes |
| No bytecode written | yes |
| Network isolation for generated tests | **no** |
| Filesystem sandbox | **no** |
| Resource limits (memory, processes) | **no** |

On a GitHub-hosted runner the job container is destroyed after the run and the
code under test is your own, so the residual risk is comparable to running your
own test suite. **On a self-hosted runner or a developer laptop, this is not
sufficient.** A pluggable sandbox backend (E2B microVM, microsandbox) is planned
for v0.4. Until then, do not run jittest locally against untrusted diffs.

### Secrets

jittest sends diff hunks and surrounding source to your chosen LLM provider.
If your diff contains secrets, they are sent. Consider:

- a provider with a zero-retention agreement,
- a self-hosted model via LiteLLM's local provider support,
- excluding sensitive paths (planned: `.jittestignore`).

jittest never transmits your ledger. It is local SQLite and export is manual.

### Prompt injection through diffs

A malicious PR can place instructions in a comment or docstring, and those text
spans reach the generator prompt. The mitigation is structural rather than
textual: **nothing the model says can produce a finding.** Only a test that
mechanically passes on base and fails on head is ever reported. The worst
outcome from an injected diff is a wasted token budget, not a false report.

This is a real advantage of the mechanical oracle and it should be stated
plainly rather than oversold.

## Reporting a vulnerability

Open a GitHub security advisory, or email the maintainer address in the README.
Response within 72 hours. Please do not open a public issue for anything
exploitable.
