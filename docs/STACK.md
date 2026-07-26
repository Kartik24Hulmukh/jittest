# Technology and repos we are leveraging

The rule: **write only the differential oracle, the risk targeter, the assessor,
and the ledger.** Everything else is a dependency. If you find yourself building
infrastructure, stop and find the library.

---

## Runtime dependencies (small on purpose)

| Need | Choice | Repo / package | Why this one |
|---|---|---|---|
| Parse unified diffs | **unidiff** | `matiasb/python-unidiff` | Battle-tested, tiny, gives per-line source/target line numbers, which is exactly what symbol mapping needs. Do not hand-roll. |
| Map lines to functions | **stdlib `ast`** | - | Zero dependency, gives `lineno` and `end_lineno`. Tree-sitter only when we add non-Python languages. |
| LLM access | **LiteLLM** | `BerriAI/litellm` | One interface to 100+ providers plus built-in cost accounting, which we need for the hard budget cap. Used in production by Netflix, Stripe, Greptile. Note: slow cold start; acceptable in CI. |
| CLI | **Typer** + **Rich** | `fastapi/typer` | Least ceremony, good help output. |
| Config/validation | **Pydantic v2** | `pydantic/pydantic` | Already transitively present via LiteLLM. |
| Test execution | **pytest** subprocess | `pytest-dev/pytest` | We run the user's own runner rather than reimplementing collection. |
| Corpus storage | **SQLite** (stdlib) | - | Inspectable, diffable, zero infra. Do not add Postgres before you have users. |
| Isolation | **git worktree** + subprocess timeout | - | The CI runner is already disposable. See below before adding more. |

**Deliberately NOT dependencies at v0.1:** LangChain, LlamaIndex, any agent
framework, any vector database, Docker at runtime, Postgres, Redis, a web app.
Every one of these is a week you do not have.

---

## Isolation: why git worktree is enough for v0.1

We execute LLM-generated code. That is genuinely dangerous - but in CI the
runner is an ephemeral container that is destroyed after the job, and the code
under test is the user's own repository.

v0.1 mitigations: hard subprocess timeout, no network in the generator prompt
contract, `PYTHONDONTWRITEBYTECODE`, temp worktrees removed on exit.

**When someone wants to run jittest locally or on a self-hosted runner, this is
not enough.** Pluggable backend lands in v0.4. Evaluated options:

| Backend | Isolation | Notes |
|---|---|---|
| **E2B** | Firecracker microVM, dedicated kernel | Strongest isolation, good SDK, hosted |
| **Daytona** | gVisor / containers, stateful | Persistent workspaces suit iterative agents |
| **Microsandbox** | libkrun microVM, local, rootless | Best for the self-hosted and air-gapped case |
| **Modal / Beam** | serverless sandboxes | GPU support we do not need |
| **Judge0** | many languages, short bursts | Overkill |

Recommendation: keep the `Worktree` interface, add `E2BBackend` and
`MicrosandboxBackend` behind it. Do not do this before v0.4.

---

## Evaluation stack

| Need | Choice | Repo |
|---|---|---|
| Real Python bugs | **BugsInPy** (493 bugs) | `soarsmu/BugsInPy`, Cerberus fork `nus-apr/bugs-in-py-benchmark` |
| Real Java bugs | **Defects4J 3.0.1** (854 bugs) | `rjust/defects4j` |
| Low-memorisation bugs | **GitBug-Java** | `gitbugactions/gitbug-java` |
| Synthetic regressions | **Cosmic Ray** or **mutmut** | `sixty-north/cosmic-ray`, `boxed/mutmut` |
| Diff coverage sanity check | **diff-cover** | `Bachmann1234/diff_cover` |

The BugsInPy inversion trick: each entry has a buggy commit and a fixed commit.
Treat `fixed -> buggy` as a synthetic regression PR. A perfect JiTTest run
produces a test that passes on `fixed` and fails on `buggy`. **The dataset ships
with the ground-truth triggering test, so we can measure catch rate exactly.**
This is the single highest-leverage thing in the whole eval design.

Watch for data leakage: BugsInPy and Defects4J are in The Stack and models
memorise them. Report GitBug-Java numbers alongside, and hold out a private set
of recent real regressions.

---

## Packaging and distribution

| Need | Choice | Why |
|---|---|---|
| Build backend | **Hatchling** | Sane defaults, trivial GitHub Actions release |
| Lint/format | **Ruff** | One tool, fast |
| CI | **GitHub Actions** | Where the users are |
| Distribution surface | **Composite GitHub Action** | Not Docker: composite actions start faster and let the target repo's own environment install itself |
| Registry | PyPI + GitHub Marketplace | Two search surfaces for one artifact |
| Docs | **MkDocs Material** | Ship at v0.3, not before. README first. |

---

## Reference implementations worth reading (do not copy, read)

| Repo | Read it for |
|---|---|
| `qodo-ai/qodo-cover` | The whole prior generation. Read `cover_agent/` for the generate-run-refine loop. Note what it does on test failure - and do the opposite. |
| `Codium-ai/pr-agent` | Mature PR-comment UX, diff compression for token limits, GitHub/GitLab/Bitbucket abstraction |
| `neu-se/testpilot2` | Academic LLM unit-test generation, prompt design |
| `sixty-north/cosmic-ray` | Distributed mutation execution and result storage |
| `Bachmann1234/diff_cover` | Clean model for mapping coverage onto diff lines |
| `rjust/defects4j` | The gold standard for a bug-benchmark harness API |

---

## Cost model (the constraint that shapes the design)

Assume 5 targets per PR, 4 candidates each, roughly 6k input and 800 output
tokens per generation, plus one assessor call per mechanically-catching
candidate.

- Generation: 20 calls, approximately $0.30-0.60 per PR on a mid-tier model
- Assessment: typically 1-3 calls, approximately $0.05-0.15
- Execution: 40-60 pytest invocations, dominated by CI minutes, not tokens

**Approximately $0.50 per analysed PR.** That is why `risk.py` exists. Running
on every PR is a business-model error, not just a bill. Meta ran on high-risk
diffs overnight on spare capacity for precisely this reason.

Default posture: analyse at most the top 5 risky symbols, cap at $1.00 per PR,
skip drafts and dependabot.
