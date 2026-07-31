# Examples

## Seeded regression demo — the whole pipeline in one command

```bash
python examples/seeded_regression_demo.py
```

What it does, end to end:

1. Creates a throwaway git repository with a tiny `calc.py`.
2. Commits a correct version on the base commit, then a version with the
   zero-floor clamp removed on the head commit — a real regression.
3. Runs `jittest run --repo <demo> --base HEAD~1 --head HEAD --dry-run
   --risk-threshold 0.0` against it, with a stub model: no API key, no
   network, no cost. The threshold is lowered so the single changed symbol is
   always analysed — the demo is about the pipeline's mechanics, not the risk
   gate's calibration.

What a dry run actually shows you, honestly:

- the real diff parser finding the changed symbol,
- the risk ranker scoring it and the gate passing it through,
- the stub model standing in for the generator (it returns no candidates by
  design — that is what "stub" means),
- and the report telling you exactly which stage ran.

A dry run does **not** execute the oracle, because a stub model produces no
candidates. To see candidates generated, executed against both commits and
assessed, install jittest, set `JITTEST_API_KEY` and drop `--dry-run`:

```bash
pip install jittest
export JITTEST_API_KEY=sk-...
python examples/seeded_regression_demo.py --keep   # note the printed repo path
jittest run --repo <printed-path> --base HEAD~1 --head HEAD --risk-threshold 0.0
```

The demo repository is deleted afterwards unless you pass `--keep`.

Nothing in this directory is required to use jittest; it exists so you can
watch the tool's mechanics before you point it at your own pull requests.
