# Architecture

```
  git diff base...head
         |
  [1] diff.py        unidiff + ast  ->  ChangeTarget per changed function
         |
  [2] risk.py        Diff Risk Score  ->  top-K risky symbols only
         |                                (cost gate: most diffs stop here)
  [3] prompts.py     inverted objective: write a test that FAILS on head
      llm.py         LiteLLM, n candidates per target
         |
  [4] execute.py     THE ORACLE - mechanical, no LLM
         |             run on head  -> must FAIL   (else: hardening test, discard)
         |             rerun x2     -> must FAIL   (else: flaky, discard)
         |             run on base  -> must PASS   (else: pre-existing, backlog)
         |
  [5] assess.py      regression | intended_change | invalid_test
         |             precision stage. ~70% review-load reduction lives here.
         |
  [6] report.py      one PR comment, edited in place, silent when empty
         |
  [7] ledger.py      every candidate + verdict + human outcome -> SQLite
                       the only part that compounds
```

---

## The four design commitments

### 1. The oracle is mechanical, not model-judged
A model never decides whether a test is a catching test. Execution does. This is
what separates jittest from every "AI finds bugs in your PR" tool: our findings
are reproducible by the reviewer in one command. When a model is wrong we waste
tokens; we do not waste the reviewer's trust.

### 2. Silence is the default output
Most PRs should produce no comment. The failure mode that kills this category is
noise. Every threshold in the codebase (`risk_threshold`, `MIN_CONFIDENCE`,
`max_targets`) is tuned toward silence. Move them up on evidence, never down for
demo purposes.

### 3. The assessor is the product; the generator is a commodity
An LLM-plus-test-runner is six weeks of work for any competent team, and at
least one company with $120M raised has the exact prior art. What is not
copyable is a labelled corpus of `(diff, candidate test, mechanical outcome,
human decision)`. `ledger.py` exists from commit one for this reason, even
though at v0.1 it does nothing but record.

Roadmap for the corpus:
- v0.1 record everything locally
- v0.2 capture thumbs-up/down reactions on PR comments as `human_outcome`
- v0.3 opt-in anonymised upload
- v0.4 replace `MIN_CONFIDENCE` with a calibrated classifier trained on it
- v0.5 publish the corpus as an open benchmark - the citation flywheel

### 4. Cost is a first-class constraint
Hard budget cap per run, enforced mid-loop, not after. A tool that surprises
someone with a bill gets uninstalled and posted about.

---

## Extension points (in the order they should be built)

| Point | Interface | Version |
|---|---|---|
| Sandbox backend | `execute.Worktree` -> `SandboxBackend` protocol | v0.4 |
| Language | `diff._enclosing_symbols` -> tree-sitter grammar per language | v0.6 (Java first, for Defects4J) |
| Risk model | `risk.score_target` -> learned model from ledger | v0.4 |
| Test runner | pytest subprocess -> runner plugin (unittest, JUnit) | v0.6 |
| Forge | GitHub `gh` CLI -> GitLab / Bitbucket adapters | v0.5 |

---

## What we deliberately do not build

- A web dashboard. The PR comment is the interface.
- A hosted service before 20 teams use the CLI.
- Autofix. Proposing the fix reintroduces the trust problem the oracle solves.
- A VS Code extension. Wrong surface: catching tests are a review-time artifact.
- Multi-language support at launch. One language done properly beats four done
  badly, and Python is where the AIDev agentic-PR evidence is.
