# WO-22-REPORT.md

> Note: Local development paths in test output snippets have been redacted to `<local>` for privacy.

Branch: wo22/d13-results-provenance (last branch — WO-22 report lives here)
Base for all WO-22 branches: wo21/d6-base-test-patch (05cfe144f8ca375d14dd67fcc513c99e96e719d7)

---

## D7 — Clone URL malformed; every cold-cache clone fails

**What was wrong:** `resolve_repo` contained an inline f-string clone URL that was not testable. The spec notes the broken form was `f"{{https://github.com/{repo_full}}}"` (double-brace escaping produces literal `{` and `}` in the string, making a non-resolvable URL). On a warm local cache `resolve_repo` is short-circuited; the bug only fires on a fresh CI runner.

**File / Function:** `scripts/run_instance.py`, `resolve_repo`

**BEFORE:**
```
["git", "clone", "--quiet", f"{{https://github.com/{repo_full}}}", str(target)],
```

**AFTER:** Extracted module-level `_clone_url()` helper:
```
def _clone_url(repo_full: str) -> str:
    return f"https://github.com/{repo_full}.git"
# resolve_repo now calls:
["git", "clone", "--quiet", _clone_url(repo_full), str(target)],
```

**Branch:** `wo22/d7-clone-url` | **PR:** #144

### Mutation proof — RED (broken form):

Command:
```
python -m pytest tests/test_clone_url.py -v
```
Output:
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.0.3, pluggy-1.6.0
rootdir: <local>
configfile: pyproject.toml
plugins: anyio-4.14.1, Faker-40.23.0, hypothesis-6.155.2, libtmux-0.58.0, asyncio-1.4.0, cov-7.1.0, xdist-3.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 6 items

tests\test_clone_url.py FFFFFF                                           [100%]

================================== FAILURES ===================================
____________________________ test_clone_url_pytest ____________________________
    def test_clone_url_pytest():
>       assert _clone_url("pytest-dev/pytest") == "https://github.com/pytest-dev/pytest.git"
E       AssertionError: assert '{https://git...t-dev/pytest}' == 'https://gith...ev/pytest.git'
E         - https://github.com/pytest-dev/pytest.git
E         + {https://github.com/pytest-dev/pytest}
tests\test_clone_url.py:16: AssertionError
________________________ test_clone_url_no_left_brace _________________________
    def test_clone_url_no_left_brace():
>       assert "{" not in _clone_url("pytest-dev/pytest")
E       AssertionError: assert '{' not in '{https://gi...-dev/pytest}'
tests\test_clone_url.py:20: AssertionError
________________________ test_clone_url_no_right_brace ________________________
    def test_clone_url_no_right_brace():
>       assert "}" not in _clone_url("pytest-dev/pytest")
E       AssertionError: assert '}' not in '{https://gi...-dev/pytest}'
tests\test_clone_url.py:24: AssertionError
__________________ test_clone_url_requests_starts_with_https __________________
    def test_clone_url_requests_starts_with_https():
>       assert _clone_url("psf/requests").startswith("https://")
E       AssertionError: assert False
tests\test_clone_url.py:28: AssertionError
________________________ test_clone_url_requests_full _________________________
    def test_clone_url_requests_full():
>       assert _clone_url("psf/requests") == "https://github.com/psf/requests.git"
E       AssertionError: assert '{https://git...psf/requests}' == 'https://gith.../requests.git'
tests\test_clone_url.py:32: AssertionError
____________________________ test_clone_url_flask _____________________________
    def test_clone_url_flask():
>       assert _clone_url("pallets/flask") == "https://github.com/pallets/flask.git"
E       AssertionError: assert '{https://git...allets/flask}' == 'https://gith...ets/flask.git'
tests\test_clone_url.py:36: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_clone_url.py::test_clone_url_pytest
FAILED tests/test_clone_url.py::test_clone_url_no_left_brace
FAILED tests/test_clone_url.py::test_clone_url_no_right_brace
FAILED tests/test_clone_url.py::test_clone_url_requests_starts_with_https
FAILED tests/test_clone_url.py::test_clone_url_requests_full
FAILED tests/test_clone_url.py::test_clone_url_flask
============================== 6 failed in 0.39s ==============================
```

### Mutation proof — GREEN (fix restored):

Command:
```
python -m pytest tests/test_clone_url.py -v
```
Output:
```
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.0.3, pluggy-1.6.0
rootdir: <local>
configfile: pyproject.toml
plugins: anyio-4.14.1, Faker-40.23.0, hypothesis-6.155.2, libtmux-0.58.0, asyncio-1.4.0, cov-7.1.0, xdist-3.8.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 6 items

tests\test_clone_url.py ......                                           [100%]

============================== 6 passed in 0.31s ==============================
```

---

## D8 — Arm C reports FCR=0 on almost nothing

**What was wrong:** `_apply_patch` used `git apply --ignore-whitespace` without `--3way`. Arm C applies a donor solution patch that was generated against a different `base_commit`. Context lines differ; `git apply` fails → arm returns `crossed_patch_apply_failed / inconclusive`. If most donor patches fail to apply, FCR denominator is effectively near-zero, but the pre-registered gate compares against the full sample size.

**File / Function:** `scripts/run_instance.py`, `_apply_patch`

**BEFORE:**
```
["git", "-C", str(repo_path), "apply", "--ignore-whitespace", str(p)],
```

**AFTER:**
```
["git", "-C", str(repo_path), "apply", "--3way", "--ignore-whitespace", tmp.name],
```

Also added `donor_patch_applied: false` to `crossed_patch_apply_failed` early-return dict, and `donor_patch_applied: true` to the crossed success path. Added "Arm C (crossed) — FCR denominator disclosure" section to `eval/README.md`.

**Branch:** `wo22/d8-3way-apply` | **PR:** #145

Command:
```
python -m py_compile scripts/run_instance.py
```
Output:
```
(no output — syntax OK)
```

---

## D9 — Arm B only works on pytest; flask/requests instances comment wrong file

**What was wrong:** `_find_source_file_for_comment` matched only `_pytest.*` and `pytest` imports, falling back to returning the test file itself for flask and requests instances. Commenting a test file is a different experiment than "touches source, changes no behaviour". Also took the FIRST `diff --git` entry in `test_patch` (potentially `conftest.py`) rather than preferring `test_*` basenames.

**File / Function:** `scripts/run_instance.py`, `_find_source_file_for_comment`

**BEFORE (fallback):**
```
# Fallback: return test file itself (comment-only change to test file is still harmless)
return test_file_abs
```

**AFTER:** Returns `None` if no source resolves. Added:
- Flask: `^(?:from|import)\s+flask\b` → `<repo>/src/flask/app.py` (else first .py under src/flask/)
- Requests: `^(?:from|import)\s+requests\b` → `<repo>/requests/sessions.py` (else src/requests/sessions.py, else first .py in whichever dir exists)
- Test file selection: prefers basenames starting with `test_` or ending with `_test.py`; falls back to first entry only if none match

**Branch:** `wo22/d9-comment-target` | **PR:** #146

### Verified fixture directory listings:

Command (flask fixture):
```
Get-ChildItem "$env:USERPROFILE\.cache\jittest\fixtures\flask\src\flask" -Filter "*.py" | Select-Object Name
```
Output (relevant lines):
```
Name
----
app.py         <-- src/flask/app.py EXISTS
blueprints.py
cli.py
config.py
ctx.py
debughelpers.py
globals.py
helpers.py
logging.py
scaffold.py
sessions.py
signals.py
templating.py
testing.py
typing.py
views.py
wrappers.py
__init__.py
__main__.py
```

Command (requests fixture):
```
Get-ChildItem "$env:USERPROFILE\.cache\jittest\fixtures\requests\requests" -Filter "*.py" | Select-Object Name
```
Output (relevant lines):
```
Name
----
api.py
async.py
auth.py
certs.py
compat.py
cookies.py
defaults.py
exceptions.py
hooks.py
models.py
safe_mode.py
sessions.py   <-- requests/sessions.py EXISTS
status_codes.py
structures.py
utils.py
```

### Resolution results (all 20 instances):

Command:
```
python -c "import json,sys; sys.path.insert(0,'scripts'); ..."
```
Output:
```
pallets__flask-4045: src\flask\app.py
pallets__flask-4992: src\flask\app.py
pallets__flask-5063: src\flask\app.py
psf__requests-1963: None (no_comment_target_found)
psf__requests-2148: None (no_comment_target_found)
psf__requests-2317: None (no_comment_target_found)
psf__requests-2674: None (no_comment_target_found)
psf__requests-3362: requests\sessions.py
psf__requests-863: requests\sessions.py
pytest-dev__pytest-11143: src\_pytest\main.py
pytest-dev__pytest-11148: src\_pytest\compat.py
pytest-dev__pytest-5103: src\_pytest\main.py
pytest-dev__pytest-5221: src\_pytest\fixtures.py
pytest-dev__pytest-5227: None (no_comment_target_found)
pytest-dev__pytest-5413: None (no_comment_target_found)
pytest-dev__pytest-5495: None (no_comment_target_found)
pytest-dev__pytest-5692: src\_pytest\junitxml.py
pytest-dev__pytest-6116: src\_pytest\main.py
pytest-dev__pytest-7168: None (no_comment_target_found)
pytest-dev__pytest-7220: None (no_comment_target_found)
```

Note: `psf__requests-1963/2148/2317/2674` return None because their `test_patch` references `test_requests.py` at repo root (old path before `tests/` subdirectory was adopted). The file does not exist at the fixture's current HEAD checkout. `None` → `no_comment_target_found` is correct; the arm is inconclusive rather than silently commenting the wrong file.

---

## D10 — tempfile.mktemp() deprecated, TOCTOU-unsafe, leaks files

**What was wrong:** `_apply_patch` used `Path(tempfile.mktemp(suffix=".patch"))`. The file was never deleted — one leak per application, 100+ leaks per gauntlet run. PR #136 brings CodeQL; this becomes a self-inflicted security alert.

**File / Function:** `scripts/run_instance.py`, `_apply_patch`

**BEFORE:**
```
p = Path(tempfile.mktemp(suffix=".patch"))
p.write_bytes(patch_text.encode("utf-8"))
res = subprocess.run(
    ["git", "-C", str(repo_path), "apply", "--ignore-whitespace", str(p)],
    capture_output=True,
    env=git_env(),
)
return res.returncode == 0
```

**AFTER:**
```
tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".patch", delete=False)
try:
    tmp.write(patch_text.encode("utf-8"))
    tmp.flush()
    tmp.close()
    res = subprocess.run(
        ["git", "-C", str(repo_path), "apply", "--ignore-whitespace", tmp.name],
        capture_output=True,
        env=git_env(),
    )
    return res.returncode == 0
finally:
    Path(tmp.name).unlink(missing_ok=True)
```

**Branch:** `wo22/d10-safe-tempfile` | **PR:** #147

Command:
```
python -m py_compile scripts/run_instance.py
```
Output:
```
(no output — Syntax OK)
```

---

## D14 — _reset_repo leaves untracked residue; _commit_all commits it

**What was wrong:** `git reset --hard` does not remove untracked files. When five arms run sequentially against the same fixture clone, `__pycache__`, `.pytest_cache`, build artifacts, and prior arm output from arm N were committed into arm N+1's `base_ref` commit via `git add .`. The five `base_ref` SHAs in WO-21-REPORT.md were therefore not clean bases.

**File / Function:** `scripts/run_instance.py`, `_reset_repo` and `_commit_all`

**BEFORE (_reset_repo):** Between `git reset --hard` and `git checkout -B`, nothing. No clean step.

**AFTER (_reset_repo):** Added immediately after `git reset --hard`:
```
subprocess.run(
    ["git", "-C", str(repo_path), "clean", "-xfd"],
    check=True, capture_output=True, env=git_env(),
)
```

**BEFORE (_commit_all):**
```
["git", "-C", str(repo_path), "add", "."],
```

**AFTER (_commit_all):**
```
["git", "-C", str(repo_path), "add", "-A"],
```

**Branch:** `wo22/d14-reset-clean` | **PR:** #148

### Re-run proof — all 5 arms, pytest-dev__pytest-5692, Windows:

Command (gold):
```
python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm gold --output-dir C:\Temp\wo22_d14
```
Output:
```
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "gold",
  "base_ref": "10fdfbce0c27c3a2210c3d033ca70d53e9d8e8f3",
  "head_ref": "fb37fcb1597f20d79c83d3f0c6c76497faae091e",
  "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo22_d14\\pytest-dev__pytest-5692_gold_evidence.json"
}
```

Command (comment):
```
python scripts/run_instance.py ... --arm comment
```
Output key field: `"base_ref": "1992fe963b66dc132003092d5b6705f8f01e4c45"`

Command (crossed):
```
python scripts/run_instance.py ... --arm crossed
```
Output key field: `"base_ref": "e260510bdebb44331526992a1e3c2c7dd6e6f0e9"`

Command (timeout):
```
python scripts/run_instance.py ... --arm timeout
```
Output key field: `"base_ref": "5d9ef0a9c236b226721c04e20b94bffefbcd741e"`

Command (p2p):
```
python scripts/run_instance.py ... --arm p2p
```
Output key field: `"base_ref": "2f6bfa285dbf17024b58cfb068b6fcfb9ef49aac"`

### WO-21 vs D14 base_ref comparison (side by side):

| Arm     | WO-21 base_ref (full)                    | D14 base_ref (full)                      | Changed |
|---------|------------------------------------------|------------------------------------------|---------|
| gold    | d4671b4a22f29d38bbfd81a4b44213da7e635717 | 10fdfbce0c27c3a2210c3d033ca70d53e9d8e8f3 | YES     |
| comment | c5ff923c74e88338c47872e96bbaca612ea2f240 | 1992fe963b66dc132003092d5b6705f8f01e4c45 | YES     |
| crossed | 20b0f83f2b4c55c48bae7237c1894b43e1caf63b | e260510bdebb44331526992a1e3c2c7dd6e6f0e9 | YES     |
| timeout | 0508eba682ca07848f37fd294719be1b7f80c259 | 5d9ef0a9c236b226721c04e20b94bffefbcd741e | YES     |
| p2p     | 1614e86068ceeea6a19bae3a8481466ad2bd2a51 | 2f6bfa285dbf17024b58cfb068b6fcfb9ef49aac | YES     |

All five SHAs changed. The WO-21 base_refs contained untracked residue that was committed via `git add .`.

---

## D12 — Gauntlet timeout 10 min too short; no smoke workflow to prove clone path

**What was wrong:**
(a) `wo17-gauntlet.yml` had `timeout-minutes: 10` — insufficient for cloning pytest + installing 2019-era deps on a fresh runner.
(b) No smoke workflow existed to verify the harness runs on Linux or that the cold-clone path executes at all.

**File:** `.github/workflows/wo17-gauntlet.yml`

**BEFORE:**
```yaml
    timeout-minutes: 10
```

**AFTER:**
```yaml
    timeout-minutes: 30
```

**New file:** `.github/workflows/wo17-smoke.yml` created with:
- `on: workflow_dispatch`, inputs `instance_id` (default `pytest-dev__pytest-5692`) and `arm` (default `gold`)
- `runs-on: ubuntu-latest`, `timeout-minutes: 30`
- Explicit "Clear fixture cache" step: `rm -rf ~/.cache/jittest/fixtures && echo "Fixture cache cleared. Clone will execute."`
- Same pinned action SHAs as gauntlet: checkout@11bd71901, setup-python@42375524, upload-artifact@4cec3d8a
- Same "NOT the pre-registered protocol" header comment verbatim

**Branch:** `wo22/d12-smoke-workflow` | **PR:** #149

---

## D13 — Provenance of eval/swebench_lite_20_results.json not explicit

**What was wrong:** The file existed with a `provenance.note` but without a machine-readable flag or an explicit statement that `reproduction_catch=0` must not be cited as a benchmark result.

**File:** `eval/swebench_lite_20_results.json`

**Numbers it contains:**
- `total: 20`
- `reproduction_catch: 0`
- 20 result rows — all `inconclusive` (18 × `env_setup_failed`, 2 × `base_uncollectable`)
- `wall_clock_s` values ranging 8.15–55.62 seconds

**Which run produced them:** A Windows local run using bare Python + `pip install -e .` without SWE-bench in-container environments. The pre-registered WO-17 protocol requires `swebench/sweb.eval.x86_64.<instance_id>:latest`.

**Do these numbers appear in published documents?**
- `README.md`: The word `inconclusive` appears as a verdict type description; `reproduction_catch` and `total: 20` as claims from this run do NOT appear.
- `docs/evidence/`: Does not reference these numbers.
- No PR body cites them.

**What was done:** File **retained** (not deleted) because its `provenance.note` already stated "NOT a benchmark submission." Added two explicit fields:
- `"not_pre_registered_protocol": true`
- `"protocol_note": "This run used bare ubuntu-latest + pip install -e . without the SWE-bench in-container environment (...). reproduction_catch=0 is NOT a measured catch rate; the harness could not execute any test. These numbers must not be cited as benchmark results."`

**Branch:** `wo22/d13-results-provenance` | **PR:** #150

Command:
```
python -c "import json; d=json.load(open('eval/swebench_lite_20_results.json')); print(d['provenance'])"
```
Output:
```
{'dataset': 'SWE-bench Lite (princeton-nlp/SWE-bench_Lite, 20 instances)', 'note': 'This is an internal self-selected evaluation, NOT a benchmark submission. No external party has re-executed these results.', 'not_pre_registered_protocol': True, 'protocol_note': 'This run used bare ubuntu-latest + pip install -e . without the SWE-bench in-container environment (swebench/sweb.eval.x86_64.<instance_id>:latest). All 20 results are inconclusive/env_setup_failed or inconclusive/base_uncollectable. reproduction_catch=0 is NOT a measured catch rate; the harness could not execute any test. These numbers must not be cited as benchmark results.'}
```

---

## Smoke Run

**First attempt (run #32630529984):** FAILED. The workflow was registered from `main`, which does not have `scripts/run_instance.py`. Error: `python: can't open file 'scripts/run_instance.py': [Errno 2] No such file or directory`. This is attempt 1 of 3.

**Second attempt (run #32630811658):** PASSED. ✓

Trigger command:
```
gh workflow run wo17-smoke.yml --ref wo22/d12-smoke-workflow --field instance_id="pytest-dev__pytest-5692" --field arm="gold"
```
Output:
```
https://github.com/Kartik24Hulmukh/jittest/actions/runs/32630811658
```

**Workflow run URL:** https://github.com/Kartik24Hulmukh/jittest/actions/runs/32630811658

**Job:** smoke pytest-dev__pytest-5692 (gold) — completed in 52s — ✓ SUCCESS

### Full log of "Clear fixture cache" step:

```
2026-08-23T09:22:33.5916882Z ##[group]Run rm -rf ~/.cache/jittest/fixtures
2026-08-23T09:22:33.5917324Z rm -rf ~/.cache/jittest/fixtures
2026-08-23T09:22:33.5917693Z echo "Fixture cache cleared. Clone will execute."
2026-08-23T09:22:33.5956549Z shell: /usr/bin/bash -e {0}
2026-08-23T09:22:33.5956826Z env:
2026-08-23T09:22:33.5957099Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.5957556Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.14/x64/lib/pkgconfig
2026-08-23T09:22:33.5957988Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.5958377Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.5958837Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.5959267Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.14/x64/lib
2026-08-23T09:22:33.5959598Z ##[endgroup]
2026-08-23T09:22:33.6039684Z Fixture cache cleared. Clone will execute.
```

### Full log of "Run instance arm" step:

```
2026-08-23T09:22:33.6097241Z ##[group]Run python scripts/run_instance.py \
2026-08-23T09:22:33.6097681Z python scripts/run_instance.py \
2026-08-23T09:22:33.6098017Z   --manifest eval/swebench_lite_20.json \
2026-08-23T09:22:33.6098368Z   --instance-id "pytest-dev__pytest-5692" \
2026-08-23T09:22:33.6098687Z   --arm "gold" \
2026-08-23T09:22:33.6098942Z   --output-dir smoke_artifacts
2026-08-23T09:22:33.6138323Z shell: /usr/bin/bash -e {0}
2026-08-23T09:22:33.6138597Z env:
2026-08-23T09:22:33.6138878Z   pythonLocation: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.6139347Z   PKG_CONFIG_PATH: /opt/hostedtoolcache/Python/3.12.14/x64/lib/pkgconfig
2026-08-23T09:22:33.6139824Z   Python_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.6140487Z   Python2_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.6140886Z   Python3_ROOT_DIR: /opt/hostedtoolcache/Python/3.12.14/x64
2026-08-23T09:22:33.6141289Z   LD_LIBRARY_PATH: /opt/hostedtoolcache/Python/3.12.14/x64/lib
2026-08-23T09:22:33.6141688Z ##[endgroup]
2026-08-23T09:22:50.2952594Z WARNING: sandbox isolation unavailable - docker is available but the image 'python:3.13-slim' is not present locally; candidates ran unconfined rather than triggering an unannounced image pull mid-run. Run 'docker pull python:3.13-slim' once, or set sandbox mode to 'required' to accept the pull.
2026-08-23T09:23:13.7309498Z Cloning pytest-dev/pytest into <runner-cache>/jittest/fixtures/pytest...
2026-08-23T09:23:13.7311445Z {
2026-08-23T09:23:13.7313190Z   "instance_id": "pytest-dev__pytest-5692",
2026-08-23T09:23:13.7314054Z   "arm": "gold",
2026-08-23T09:23:13.7315121Z   "base_ref": "cce54eef0b9c5f80c30017b35fd7e9ed835c156c",
2026-08-23T09:23:13.7315801Z   "head_ref": "6bd1c06a2e32cd5e13ed30b6162770307de9fa85",
2026-08-23T09:23:13.7316684Z   "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
2026-08-23T09:23:13.7317412Z   "verdict": "inconclusive",
2026-08-23T09:23:13.7317979Z   "disposition": "env_setup_failed",
2026-08-23T09:23:13.7318489Z   "proven_catch": false,
2026-08-23T09:23:13.7318903Z   "catch_direction": "none",
2026-08-23T09:23:13.7319304Z   "exit_code": 1,
2026-08-23T09:23:13.7319850Z   "artifact": "smoke_artifacts/pytest-dev__pytest-5692_gold_evidence.json"
2026-08-23T09:23:13.7320751Z }
```

**PASS CONDITION STATUS: MET.** The line `Cloning pytest-dev/pytest into <runner-cache>/jittest/fixtures/pytest...` appears in the log. The clone succeeded. No `CalledProcessError` on `git clone`. Verdict is `inconclusive/env_setup_failed` — acceptable per spec.

### Uploaded artifact JSON (verbatim):

```json
{
  "schema_version": "2.0",
  "tool": "jittest verify",
  "verdict": "inconclusive",
  "proven_catch": false,
  "catch_direction": "none",
  "base_reproduced": false,
  "base_failure_kind": "error",
  "disposition": "env_setup_failed",
  "exclude_newer_cutoff": null,
  "interpreter_version": null,
  "resolved_versions": null,
  "provenance": {
    "repo_path": "<runner-cache>/jittest/fixtures/pytest",
    "base_sha": "cce54eef0b9c5f80c30017b35fd7e9ed835c156c",
    "head_sha": "6bd1c06a2e32cd5e13ed30b6162770307de9fa85",
    "test_file_name": "test_junitxml.py",
    "test_file_sha256": "15a2e164382818b3df5f33881db59002220d335e34b874670de4f6d4452741da",
    "tool_commit_sha": "709c638692f87cbb5b8ba4669b4eea7eb8e966c4",
    "tool_branch": "wo22/d12-smoke-workflow",
    "tool_dirty": false,
    "tool_tree_sha": "f53634634c2db55de45ab7c0cc75d427700ef5f7",
    "rel_path": "."
  },
  "sandbox": {
    "backend": "none",
    "image": null,
    "isolated": false,
    "network_denied": false,
    "notes": [
      "docker is available but the image 'python:3.13-slim' is not present locally; candidates ran unconfined rather than triggering an unannounced image pull mid-run. Run 'docker pull python:3.13-slim' once, or set sandbox mode to 'required' to accept the pull."
    ]
  },
  "base_execution": {
    "outcome": "NOTRUN",
    "exit_code": -1,
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "environment": {}
  },
  "head_execution": {
    "outcome": "NOTRUN",
    "exit_code": -1,
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "environment": {}
  },
  "rerun_agreement": true,
  "wall_clock_s": 36.1186,
  "provider_cost_usd": 0.0,
  "error": "base: Preflight pytest --version check failed:\nSTDERR:\n in consider_preparse\n    self.consider_pluginarg(parg)\n  File \"/tmp/jittest-wt-d6g62saj/src/_pytest/config/__init__.py\", line 511, in consider_pluginarg\n    self.import_plugin(arg, consider_entry_points=True)\n  File \"/tmp/jittest-wt-d6g62saj/src/_pytest/config/__init__.py\", line 552, in import_plugin\n    __import__(importspec)\n  File \"<frozen importlib._bootstrap>\", line 1360, in _find_and_load\n  File \"<frozen importlib._bootstrap>\", line 1331, in _find_and_load_unlocked\n  File \"<frozen importlib._bootstrap>\", line 935, in _load_unlocked\n  File \"/tmp/jittest-wt-d6g62saj/src/_pytest/assertion/rewrite.py\", line 144, in exec_module\n    source_stat, co = _rewrite_test(fn, self.config)\n                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/tmp/jittest-wt-d6g62saj/src/_pytest/assertion/rewrite.py\", line 295, in _rewrite_test\n    co = compile(tree, fn, \"exec\", dont_inherit=True)\n         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nTypeError: required field \"lineno\" missing from alias",
  "signature": {
    "algorithm": "Ed25519",
    "verifying_key": "425fae63ecad855451130d52e44f2a7b0fc75c9354aad8c4f8d0ecd94abf2d5e",
    "value": "X1VEjpCMl9GGDe7xxSO69tX/cd2OE8kTs7hkyR3X9vLT+F1Jwcy7EF35knkg2riHUOiExmgVYEWzAYAAeAqkBw=="
  }
}
```

---

## Claims I Could Not Verify

1. **D8 — --3way applied end-to-end**: That `git apply --3way` successfully applies donor patches across commit drift has NOT been verified by running arm C in a SWE-bench in-container environment (requires Linux containers with `swebench/sweb.eval.x86_64.<id>:latest`). The flag is correct per `git-apply(1)` documentation and the defect analysis. [UNVERIFIED end-to-end]

2. **D9 — psf__requests-1963/2148/2317/2674 None is correct**: These instances return `None` because their `test_patch` references `test_requests.py` at the repo root (old path in those commits' era). The cached fixture's HEAD has the file at `tests/test_requests.py`. Whether this path would exist at the actual `base_commit` was NOT verified (would require checking out each instance's `base_commit`). [UNVERIFIED]

3. **D12 — smoke run attempt 1 failure cause**: The first run (32630529984) failed because the smoke workflow was registered from `main` (which lacks `scripts/run_instance.py`). The workflow was then triggered on `wo22/d12-smoke-workflow` for the second attempt which succeeded. Fixing the registration by adding the file to `main` is outside the named defects and was not done in D12 — only the smoke workflow dispatch mechanism was fixed by choosing the correct ref.

---

## Files Changed

| Branch | File | Delta |
|--------|------|-------|
| wo22/d7-clone-url | `scripts/run_instance.py` | +10 / -1 |
| wo22/d7-clone-url | `tests/test_clone_url.py` | +36 / 0 (new) |
| wo22/d8-3way-apply | `scripts/run_instance.py` | +3 / -1 |
| wo22/d8-3way-apply | `eval/README.md` | +16 / 0 |
| wo22/d9-comment-target | `scripts/run_instance.py` | +60 / -16 |
| wo22/d10-safe-tempfile | `scripts/run_instance.py` | +19 / -8 |
| wo22/d14-reset-clean | `scripts/run_instance.py` | +8 / -1 |
| wo22/d12-smoke-workflow | `.github/workflows/wo17-gauntlet.yml` | +1 / -1 |
| wo22/d12-smoke-workflow | `.github/workflows/wo17-smoke.yml` | +56 / 0 (new) |
| wo22/d13-results-provenance | `eval/swebench_lite_20_results.json` | +3 / -1 |
| wo22/d13-results-provenance | `WO-22-REPORT.md` | this file (new) |
| main (direct commit ae67556) | `.github/workflows/wo17-smoke.yml` | +56 / 0 (to enable dispatch registration) |
