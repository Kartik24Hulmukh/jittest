# Release artifacts: source-to-artifact mapping

Machine-readable source of truth: [`docs/release-artifacts.json`](release-artifacts.json).
Guarded by `scripts/check_release_mapping.py` (CI `no-number-drift`) and `tests/test_release_mapping.py`.

This answers one question for a user: **what exactly do I get when I `pip install jittest`?**

## Published: `jittest 0.4.1` (verified 2026-09-15)

| Field | Value |
|---|---|
| PyPI version | `0.4.1` (0.4.0 is yanked; see `YANK-REASONS.md`) |
| Git tag | `v0.4.1` |
| Source SHA | `ef08ddbca551f5d3201cc3e839d1995202bb1934` |
| Wheel | `jittest-0.4.1-py3-none-any.whl` — SHA-256 `d33eaa33cc24d0be2dd9dad5975ca4d3c6e3fb8640f008cea6988e7b6a8b6b95` |
| sdist | `jittest-0.4.1.tar.gz` — SHA-256 `1e133d4b135ccbc6914f3342cf86df12463b0dc9f5098fd409764ab1aae496a3` |
| Released | 2026-09-13 14:05 UTC (GitHub release `v0.4.1`, same assets attached) |

### How it was verified

1. Downloaded both artifacts from PyPI; SHA-256 matched the registry digests.
2. Downloaded the tag tarball for `ef08ddbc`; hashed every `src/jittest/*.py` and every `jittest/*.py` in the wheel: **43/43 modules byte-identical, 0 mismatched, 0 missing.**
3. Installed the wheel with `--no-deps` in a fresh venv; `jittest --version` printed `jittest 0.4.1`; `jittest.__version__ == "0.4.1"`.

Reproduce:

```sh
pip download --no-deps jittest==0.4.1 -d dist/
sha256sum dist/jittest-0.4.1-py3-none-any.whl   # d33eaa33...
python scripts/check_release_mapping.py          # offline consistency check
```

## What `0.4.1` does NOT contain

The published wheel predates the following merged work. Users installing from PyPI do **not** get these guarantees yet:

- #196 per-phase verification boundaries (`_run_guarded_phase`)
- #197 execution-path containment (`execution_paths.py`)
- #200 BASE runtime pin wiring
- #201 `jittest.prod` probes (`/healthz`, `/readyz`), JSON logging, OTel tracing, fixed-seed benchmarks

To evaluate them, install by exact commit SHA (`pip install git+https://github.com/Kartik24Hulmukh/jittest@<sha>`), never by mutable `main`.

## Policy

- Docs must claim only the version recorded in `release-artifacts.json`.
- Bumping the mapping requires a real release record (tag + PyPI upload); do not edit it to make docs look current.
- A new release goes through `release.yml` protected gates; this file is updated in the same PR that lands the release notes.
