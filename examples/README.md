# Examples

## Seeded regression demo — the whole pipeline in one command

```bash
python examples/seeded_regression_demo.py
```

What it does, end to end:

1. Creates a throwaway git repository with a tiny `calc.py`.
2. Commits a correct version on the base commit, then a version with the
   zero-floor clamp removed on the head commit — a real regression.
3. Runs `jittest run --repo <demo> --base HEAD~1 --head HEAD --dry-run`
   against it, with a stub model: no API key, no network, no cost.

The dry run exercises the real diff parser, the risk ranking, both git
worktrees and the differential oracle. To see the model path, install jittest,
set `JITTEST_API_KEY` and drop `--dry-run`.

The demo repository is deleted afterwards unless you pass `--keep`:

```bash
python examples/seeded_regression_demo.py --keep
```

Nothing in this directory is required to use jittest; it exists so you can
watch the tool prove a finding before you point it at your own pull requests.
