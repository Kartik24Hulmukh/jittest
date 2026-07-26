# Contributing

```bash
git clone https://github.com/Kartik24Hulmukh/jittest && cd jittest
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check src tests
```

## The one rule

**A model never decides whether a finding is real. Execution does.**

Any PR that lets an LLM verdict bypass `execute.differential_check` will be
closed. The mechanical oracle is the entire trust proposition of this project;
without it we are the fifteenth AI code reviewer.

## Where help is most valuable

1. **Language support.** `diff._enclosing_symbols` is Python-`ast` only. A
   tree-sitter backend for Java or TypeScript is the highest-impact contribution
   available. Java unlocks Defects4J.
2. **Sandbox backends.** `execute.Worktree` should become a protocol with E2B
   and microsandbox implementations for local and self-hosted runs.
3. **Risk model.** `risk.score_target` is hand-tuned heuristics standing in for
   Meta's trained Diff Risk Score. A model trained on `ledger.db` would be a
   real improvement, and it is measurable.
4. **Prompts.** Improvements must be accompanied by a before/after run of
   `eval/run_bugsinpy.py`. "Feels better" is not evidence.
5. **False-positive reduction.** The least glamorous and most valuable work.

## Evidence standard for behaviour changes

Any PR that changes generation, risk scoring, or assessment must include eval
numbers before and after on the same bug subset and the same model, plus the
cost delta. Attach the JSON. This is stricter than most projects and it is
deliberate: this project's only durable asset is that its numbers are true.

## Commit style

Conventional commits. `feat:`, `fix:`, `docs:`, `eval:`, `perf:`, `chore:`.

## Licensing

By contributing you agree your work is licensed under Apache-2.0.
