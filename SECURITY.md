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

## What the candidate safety gate is, and what it is not

jittest asks a model to write a test and then executes that test inside your CI
runner. `src/jittest/safety.py` is a static AST gate that runs before execution.
It rejects imports of dangerous modules, banned builtins (including aliases such
as `f = eval`), reflection helpers (`getattr` with a computed name,
`importlib.import_module`, `runpy`), interpreter gadgets (`__subclasses__`,
`__globals__`, `__mro__`), writes to constant filesystem paths, and vacuous
assertions.

It is not a sandbox. It is a static check, and static checks on Python are
defeatable in principle. Treat it as defence in depth, not as containment. If you
run jittest on untrusted pull requests, run it in an ephemeral runner with no
secrets beyond the model key, which is what the bundled workflow does.

One bypass class deserves specific mention because it attacks the result rather
than the host: a candidate test that writes to a source file in the worktree can
manufacture a difference between the base and head runs, and therefore forge a
catching test. The gate blocks the constant-path form of this. If you find a
variant it does not block, please report it privately.
