# Premortem, 28 July 2026 — Defects 32 to 71

Audit of commit `178b500` (v0.2.4). Three independent auditors, one scope each,
no shared context, each asked a single question: **where can this thing lie to
us?**

| Auditor | Scope | Fatal | Severe | Moderate |
|---|---|---|---|---|
| A | `diff.py`, `execute.py`, `pipeline.py` | 4 | 9 | 7 |
| B | `eval/*`, `.github/workflows/eval.yml` | 4 | 8 | 3 |
| C | `safety.py`, `report.py`, `github.py`, `prompts.py` | 5 | 8 | 5 |

No source file is modified by this commit. Registering before fixing is
deliberate: several of these fixes change *what a published number means*, and no
number has been published yet. That is a narrow and closing window.

---

## The one-paragraph version

The product is one sentence: **a catching test passes on the base commit and
fails on the head commit.** As implemented, "passes on base" means *exit code 0,
sampled once, in a shared mutable worktree that is never verified to contain
base's code.* Five defects below each independently break that clause, and four
more each independently let a run that measured nothing exit green. The oracle is
the product; the oracle is not currently enforcing its own guarantee.

---

## Class I — The oracle can certify a catch that is not one

### Defect 32 (FATAL) — `pytest` exits 0 when every test was SKIPPED, and that is read as "passes on base"

`execute.py :: run_test` maps `code == 0` to `Outcome.PASS`. Nothing parses
stdout to confirm a test executed and asserted. `differential_check` then accepts
`on_base.outcome is Outcome.PASS` as proof.

pytest exits 0 when all tests were skipped, xfailed, or deselected. The generator
is shown `source_before = "(new code, no prior version)"` whenever a symbol
cannot be found at base, so guard-based skips are a *likely* model output:

```python
try:
    from mod import new_helper
except ImportError:
    pytest.skip("not available")
```

This skips on base (symbol absent) and fails on head. Verdict:
`is_catching=True`, reason `"catching: passes on base, fails on head"`. The base
side proved nothing. **This is a fabricated catch reported with full confidence.**

*Fix:* require the base run to report `>= 1 passed` and `0 skipped` for the
target. Exit code is not evidence; the summary line is.

### Defect 33 (FATAL) — nothing verifies the worktrees contain the revisions they claim

`differential_check` accepts injected `head_workdir` / `base_workdir` — the only
path `pipeline.run` uses — and never checks either. Two arguments of identical
type; swapping them silently inverts the oracle and reports the reverse diff as
catching.

*Fix:* `git rev-parse HEAD` in each workdir, compared against the expected rev,
before any candidate runs. The most important invariant in the product is
currently enforced by caller discipline alone.

### Defect 34 (FATAL) — `PYTHONPATH` does not beat an installed distribution

`_env_for` prepends the worktree to `PYTHONPATH`. `PYTHONPATH` does not take
precedence over a package already in `site-packages`. In the standard CI setup
where the project was `pip install .`'d, **base and head execute byte-identical
code.**

Usually this yields fails-on-both, which is then filed as a *pre-existing fault*
— a positive claim the run did not earn. With `pip install -e .` pointing at the
original working tree, the oracle's result is about the dirty working tree while
still being reported as `"passes on base, fails on head"`.

*Fix:* run with `-P` / isolated mode and assert the module under test resolves
inside the worktree before trusting any verdict.

### Defect 35 (SEVERE) — worktrees are reused across candidates and never reset

Head and base worktrees are created once per run and reused for every candidate.
Only the candidate `.py` file is unlinked afterwards. Anything else a candidate
wrote persists — a data file, a cache, an `__init__.py`, and worst of all a root
`conftest.py`.

Candidate 3 writes a file; candidate 7 now passes on base because it exists and
fails on head because it does not. **False catch, attributed to the PR.**

*Fix:* `git checkout -- . && git clean -xfd` between candidates, or assert clean.

### Defect 36 (SEVERE) — reruns protect only the safe direction, and `reruns=1` silently disables them

Reruns run on head only. Head-fail is the direction that costs nothing if wrong.
**Base-pass — the direction that manufactures a false catch — is sampled exactly
once.** And `max(0, reruns - 1)` means the legal config `reruns=1` executes the
loop zero times, voiding the docstring guarantee with no warning.

### Defect 37 (SEVERE) — `rerun_agreement` is reverse-engineered from prose

`pipeline._telemetry` computes `rerun_agree = "non-deterministic" not in
verdict.reason.lower()`. For a catching verdict the reason never contains that
string, so **`rerun_agreement` is unconditionally `True`** — including when no
rerun ran (Defect 36). The report asserts corroborating evidence that does not
exist.

*Fix:* `Verdict` must carry the actual rerun count and outcomes.

### Defect 38 (SEVERE) — exit code 1 conflates "assertion failed" with "the test crashed"

A `ConnectionError`, a missing optional import, a transient `OSError` all exit 1
and are accepted as `FAIL`, i.e. as behavioural evidence. Combined with Defect
32: `FAIL` on head plus exit-0 on base is a reported catch **in which no
assertion was ever evaluated on either side.**

Also: `detect_runner()` is called inside every `run_test`, so head and base can
in principle be judged by different runners with different exit-code contracts.

### Defect 39 (SEVERE) — a base TIMEOUT is filed as a pre-existing fault

The fall-through returns `"could not be collected on base, so no comparison is
possible"` for base `ERROR` **or** `TIMEOUT`. That string contains no `"head"`,
so `_disposition_from_verdict` lands it on `head_failed_base_failed_latent` —
"fails on both." Every aggregated number counts base timeouts and base import
errors as **real negative results.**

### Defect 40 (SEVERE) — `_disposition_from_verdict` defaults to the most specific claim in the set

It substring-matches prose that lives in another module, and its catch-all is
`head_failed_base_failed_latent`. Any reword in `execute.py` silently becomes
"pre-existing fault." No import coupling, no test notices.

*Fix:* default to `unknown` and make it loud. `DISPOSITIONS` is declared and
never used to validate anything.

### Defect 41 (MODERATE) — `PYTHONHASHSEED=0` rubber-stamps the flakiness it names

Pinning the seed makes order-dependent nondeterminism reproduce *identically*
across all three executions, so the rerun loop certifies such a test as
deterministic. The reviewer, running with a random seed, sees it behave
differently. The reruns should **vary** the seed.

### Defect 42 (MODERATE) — timeout kills the child, not the process tree

Grandchildren survive, keep running against a shared worktree, hold file handles
that break `worktree remove`, and pollute later candidates (Defect 35). Kill the
process group.

---

## Class II — A run that measured nothing exits green

### Defect 43 (FATAL) — `git_diff` still collapses "error" and "empty" into `""`

The ancestor bug was fixed by adding a two-dot fallback. The *fatal property* was
not: `returncode != 0` and `stdout == ""` still return the same value, and
`stderr` is captured then discarded.

With `actions/checkout` at default `fetch-depth: 1`, `git diff base...head` fails
with `fatal: bad object`. Both specs fail. `git_diff` returns `""`. `pipeline.run`
then appends:

> "empty diff between base and head... This is a property of the revision pair,
> not a result about the code."

**That message is false in this path.** The event was a git failure. Same
signature as the original incident — zero candidates, seconds, green — different
cause.

*Fix:* distinguish "both specs exited 0 with no output" from "a spec failed", and
raise on the latter.

### Defect 44 (SEVERE) — `git_show` failure is laundered into "no target", with no error recorded

Any `git show` failure is indistinguishable from "file is empty" and the target is
dropped silently. If it fails for every file, `extract_targets` returns `[]` and
`run` returns early with **nothing in `report.errors` at all** — strictly less
honest than the empty-diff branch. A non-empty diff yielding zero targets is a
suspicious state currently reported as a quiet success.

### Defect 45 (FATAL) — a totally broken model integration produces a clean green run

`except LLMError: report.errors.append(...); continue`. Every generation call can
fail — bad key, 401, proxy, schema change — and the loop continues to the end,
returning `findings=[]`, `has_regression=False`. `Report` has **no status field**
separating "ran the oracle and found nothing" from "never ran the oracle."
`model_requests` exists but nothing compares it against expectation.

### Defect 46 (SEVERE) — systemic collection failure looks exactly like a clean PR

`import_path_for` is documented as best-effort, with a wrong guess showing up as a
collection error "which is the correct failure mode." It is the correct
*per-candidate* failure mode and the wrong *run-level* one. Namespace packages, a
`src/` layout with a differing package name, or a root `conftest.py` requiring a
custom flag makes **100% of candidates uncollectable**, and the run is
indistinguishable from "your PR is clean."

*Fix:* refuse to certify a run whose `head_uncollectable / candidates_generated`
ratio exceeds a threshold.

---

## Class III — The published numbers do not mean what they say

### Defect 47 (FATAL) — catch rate is never checked against BugsInPy's ground-truth test

`run_bugsinpy.py` docstring: *"Because BugsInPy ships the ground-truth triggering
test, catch rate is measurable exactly rather than estimated."*

`spec.test_file` is parsed — and then **never referenced again anywhere in the
file.** `evaluate_one` never runs it, never compares against it. Instead:

```python
res.reported = len([f for f in report.findings if f.assessment.should_report])
... return "caught" if reported > 0 else "missed"
```

`should_report` is an assessor verdict — **a judgement by the system under test
about itself.** `BugResult` has no `base_passed`, `head_failed`, or
`test_executed` field, so no execution evidence is stored even incidentally.

The docstring's "measurable exactly" is, on the code as written, false. **This
alone invalidates any catch rate this harness produces.**

### Defect 48 (FATAL) — `catch_rate`'s denominator deletes every failure

```python
usable = [r for r in results if r.status not in ("error", "skipped", "not_measured")]
"catch_rate": round(len(caught) / max(measured_count, 1), 3) ...
```

`error` is assigned by a blanket `except Exception` — missing commits, checkout
failures, budget exhaustion, oracle crashes. All vanish from the denominator.
There is no minimum sample size and no maximum error rate anywhere.

`attempted=50, errored=49, measured=1, caught=1` yields **`catch_rate: 1.0`**,
and the gate prints `OK: 1/50 bugs measured`.

Worse, the failures still *fund* the gate: `model_requests_total` sums over **all**
results, so bugs that errored after burning model calls supply the "we measured
something" evidence while contributing nothing to the denominator they would have
dragged down. **The harness is structurally biased upward, and the bias grows
with the failure rate.**

### Defect 49 (FATAL) — the per-bug empty-diff defect is aggregate-invisible, not impossible

The inversion is oriented correctly (`base=fixed, head=buggy`) — which is exactly
the ancestor topology behind the original incident. There is **no per-bug
assertion that the revision pair produced a non-empty diff**, that both commits
exist, or that any target was extracted.

The only defence is aggregate `model_requests_total > 0`, and aggregates cannot
detect that 49 of 50 bugs diffed to nothing — because per Defect 48 those 49
leave the denominator. **One bug with a non-empty diff launders a sweep in which
the inversion silently failed everywhere else.**

Aggravating: `clone()` reuses one clone per *project* across all its bugs with no
`git reset --hard` and no `git clean` between them.

### Defect 50 (FATAL) — `false_positives.py` prints `0.0` for a run that did nothing

No `model_requests`, no `not_measured` status, no gate, and:

```python
"false_positive_rate": round(len(noisy) / max(len(usable), 1), 3),
```

If `--repo` is not a git repo, or the window is empty, or the project
squash-merges (no merge commits at all), `clean_merges` returns `[]` and the
script prints **`false_positive_rate: 0.0`, `prs_analysed: 0`, exit 0.** A
flawless precision result from zero work.

The `max(..., 1)` idiom that `run_bugsinpy.py` was carefully corrected for
(`if measured_count > 0 else None`) was never corrected here. **Zero percent false
positives is the most attractive number this project could publish and currently
the easiest one to produce by accident.**

### Defect 51 (FATAL) — the measurement gate cannot distinguish a model call from a counter increment

`assert_measured.py`'s entire evidence is one integer supplied by the harness it
audits. No corroboration required: no non-zero cost, no tokens, no provider, no
`priced == True`. A run reporting `model_requests_total: 500, mean_cost_usd: 0.0,
priced: false` passes and prints `OK: 10/10 bugs measured across 500 model
requests`. Any stub, cache or replay layer that increments the counter satisfies
it.

### Defect 52 (SEVERE) — the gate blesses a `catch_rate` it never recomputes

The only test applied to the headline number is a range check. The gate never
counts `status == "caught"` in `results` and compares. A summary asserting
`catch_rate: 0.85` alongside two caught rows out of forty passes.

### Defect 53 (SEVERE) — the gate does not fail closed on malformed `results`, contrary to its docstring

Docstring: *"any unreadable structure fails closed."* Code:
`if not isinstance(results, list): results = []`. A payload with a well-formed
`summary` and `"results": "n/a"` passes at full strength. **The gate can certify a
run for which no per-bug evidence exists.** Also `_count` truncates non-integral
floats: `bugs_measured: 1.9` → `1`.

### Defect 54 (SEVERE) — dry-run state is never recorded anywhere

The fail-fast guard triggers on `has_key and dry_run` — inverted relative to the
risk. No key plus `--dry-run` is fully permitted, and `dry_run` is never written
into `summary` or any row. **A `results.json` from a stub run and from a paid run
are structurally indistinguishable.**

In CI, `JITTEST_API_KEY: ${{ secrets.JITTEST_API_KEY }}` is an empty string when
the secret is unset — so `has_key` is `False` and the guard is inert in exactly
the misconfiguration it was written for.

### Defect 55 (SEVERE) — cost accounting can report `$0.00` while real money was spent

Four independent mechanisms: (a) no `total_cost_usd` exists at all, only a mean
over the flattered subset; (b) `res.cost_usd` is assigned *after* `run_pipeline`
returns, so spend before a throw — including budget exhaustion — is
unattributable; (c) `priced: bool = True` defaults to a lie, so every errored row
asserts it was correctly priced at $0.00; (d) unpriced rows are averaged in as
real zeros, so `priced: false` and `mean_cost_usd: 0.312` can be printed side by
side.

`false_positives.py` reports **no cost field at all**, despite `eval/README.md`
claiming cost is "reported by both." That row of the table is false.

### Defect 56 (SEVERE) — CI institutionalises the exact publication the docs forbid

`eval/README.md`: *"Three numbers, always published together."*
`run_bugsinpy.py`: *"Pair it with the false-positive rate before publishing
anything."*

`eval.yml` runs **only** `run_bugsinpy.py`. `false_positives.py` appears nowhere.
No step checks the stated launch targets. **The only automated, artifact-producing
path in the repo emits a lone recall number — precisely the artifact the
project's own honesty rule prohibits.** The rule is documentation; the workflow is
behaviour.

### Defect 57 (SEVERE) — the two numbers are measured with different, silently divergent configs

`run_bugsinpy.py` uses `load_config` and documents why. `false_positives.py`
reintroduces the exact bug that fix removed: `Config(model=args.model or
"anthropic/claude-sonnet-4-5", ...)`, ignoring `JITTEST_MODEL` and
`JITTEST_API_BASE`. Neither script records the model it used. **Pairing them
implies a comparability that does not exist.**

### Defect 58 (SEVERE) — sampling is deterministic, single-project, and undisclosed

`discover` walks `sorted(...)` and truncates at N. With the default `limit: 10`,
every run measures **the same first ten bugs of whichever project sorts first
alphabetically** — one codebase, one test framework, one bug style. No `--seed`,
no shuffle, no stratification, and nothing in `summary` discloses this. A "catch
rate on BugsInPy" from a default run is a catch rate on ten adjacent bugs in one
project, presented with the name of a 493-bug benchmark attached.

### Defect 59 (SEVERE) — the "clean PR" selection does not implement its own documented method

Docstring: merge commits *"whose merged branch was never touched by a later commit
message containing revert, hotfix, or fixes #<pr>."* Implementation tests only the
merge commit's **own subject**. There is no scan of later history — that logic
does not exist. The "clean" set therefore includes genuinely reverted PRs, so
jittest flagging one is scored as a false positive. Wrong in the pessimistic
direction, but **the published method description is false either way.**

### Defect 60 (MODERATE) — no provenance in the artifact

Model, API base, jittest commit, BugsInPy pin and dry-run state are never written
into `results.json`. The pin is verified in a shell step whose output lives only
in expiring logs. **A published number carries no reproducible provenance.**

### Defect 61 (MODERATE) — `--project` filter is silently broken and misdiagnoses itself

`--project` is `action="append"` with exact-match comparison, but the workflow
input is documented as comma-separated and interpolated as one token.
`"black,pandas"` matches nothing, `discover` returns `[]`, and the gate fails with
*"check the BugsInPy clone and --limit"* — pointing at the wrong cause. Also
`report_suppressed` is declared, defaulted to `"true"`, and **never referenced
anywhere** — an inert control that invites a reader to believe suppressed catches
were excluded.

---

## Class IV — Untrusted input reaches execution and publication

The threat model: on a public repository, the PR title, body and diff are all
written by strangers, and jittest **executes model-written code** in a runner
holding an API key and a workflow token, then **posts a comment back.**

### Defect 62 (FATAL) — nested-call indirection bypasses the safety gate entirely

`check_candidate` inspects `Call.func` only when it is literally a `Name` or an
`Attribute`. `Call(func=Call(...))` matches neither branch. The `getattr` guard
only requires a constant second argument, which the attacker supplies:

```python
import os
def test_regression_in_clamp():
    getattr(os, "system")("...")
    assert 1 == 1
```

Variants needing no `getattr`: `operator.attrgetter("system")(os)(...)`,
`pkgutil.resolve_name("os.system")(...)`. **`os` is not in `BANNED_MODULES`.**
Arbitrary command execution in the runner.

### Defect 63 (FATAL) — attribute callables can be aliased; only builtins are protected

The alias defence covers the nine names in `BANNED_CALLS`. There is no equivalent
for attributes, and a bare `Attribute` node is checked only against
`BANNED_DUNDERS`:

```python
import os
_run = os.system
def test_old_behaviour(_x=_run("...")):   # also survives default-arg evaluation
    assert 1 == 1
```

Same trick for `_w = open`, which defeats the worktree-tamper protection the file
states it enforces.

### Defect 64 (FATAL) — secrets are reachable and the gate only *warns*

`os` is not banned, `getenv` is not in `BANNED_ATTRS`, and `os.environ[...]` is a
`Subscript` that nothing inspects. The only reaction is
`warnings.append(...)` — **and `ok=True`. Warnings do not gate.**

jittest cannot run without a model key in that environment. pytest's assertion
rewriting puts the value into failure output, which `to_markdown` renders into the
public PR comment. **Complete exfiltration of the API key and workflow token to a
public comment, with no network call — so egress filtering does not help.**

### Defect 65 (FATAL) — the module denylist omits the obvious siblings of what it bans

`socket`/`subprocess`/`urllib`/`http`/`pty` are banned. These are not, and none of
their entry points are in `BANNED_ATTRS`: `asyncio`
(`create_subprocess_exec`, `open_connection`), `os.posix_spawn` / `spawnlp` /
`forkpty` (while `spawnl`/`fork` *are* listed), `xmlrpc.client`, `sqlite3`,
`tarfile`/`zipfile` (`extractall` traversal), `fileinput` (in-place rewrite),
`io.open` / `codecs.open` / `pathlib.Path.open` (only `write_text`/`write_bytes`
are banned).

The file's own comment concedes a denylist cannot be completed. **It should be
stated in the threat model that the gate is a speed bump, not a boundary** — or
the candidate should run in a container with no network and no secrets, which is
the only version of this that actually holds.

### Defect 66 (FATAL) — prompt injection can suppress every finding, undetectably

`pr_context_block` splices `title` (untruncated) and `body` into the generator
prompt unfenced, unlabelled, and **followed by an instruction in the same plain
prose the attacker can imitate.** `NO_CANDIDATE = "# NO_CANDIDATE"` is a
documented sentinel in the same file, so the suppression path is fully specified
for the attacker.

A PR body ending in a forged `SYSTEM (generator):` block instructing the model to
emit only `# NO_CANDIDATE` removes every finding. Because `to_markdown` returns
`""` with no findings and the client answers *"skipped: nothing proven, so nothing
said"*, **the suppression is indistinguishable from a clean PR.** Silence is the
documented expected output, so nobody investigates.

The same channel lets the attacker dictate the *content* of the generated file —
which is what turns Defects 62–64 from AST gaps into a chosen payload.

### Defect 67 (SEVERE) — the assessor takes attacker text first, ahead of all evidence

`ASSESSOR_USER` places `{pr_title}` and `{pr_body}` — untruncated, unlike the
generator's 800-char cap — before the diff and the test. A forged "assessor
directive" returning `{"verdict":"intended_change","confidence":0.98}` buries a
real regression in the collapsed `<details>` block.

The mirror attack is worse: the attacker dictates `real_regression` plus arbitrary
`summary` and `reviewer_question`, which are published in the repo bot's comment.
**A malicious PR can make jittest defame an unrelated symbol, or post
attacker-written instructions to reviewers under jittest's name.**

### Defect 68 (SEVERE) — `upsert_pr_comment` matches the marker with no author check

No `user.login` comparison, no app check, first match wins. The marker is an
invisible HTML comment published in the source. An attacker posts a comment
containing it; jittest finds *that* one first and PATCHes its report into it. With
`issues: write` the PATCH succeeds, and the attacker can edit it again —
**controlling the body of the comment reviewers believe is jittest's report.**

A maintainer who quotes the report copies the invisible marker; the next run
overwrites the maintainer's comment. And `per_page=100` with no pagination means a
thread over 100 comments makes jittest post fresh every run — turning the bot into
a spammer, the exact failure the module says it exists to prevent.

### Defect 69 (SEVERE) — `--edit-last` in the CLI fallback has no marker check at all

`gh pr comment --edit-last` edits the identity's most recent comment on the PR,
whatever it is. On the tokenless and post-API-error paths, all marker discipline
is bypassed. An attacker who can force one API error chooses when this happens.

### Defect 70 (SEVERE) — `test_code` is fenced but never sanitised, and the invariant lives in an `assert`

Every other untrusted field goes through `_untrusted`; the test body does not. A
fence does not stop the marker from being *present in the body*, which is what the
upsert matches on. `assert rendered.count(MARKER) == 1` then raises and **no report
is posted at all** — silent suppression of every finding.

`f.target.qualified` is interpolated raw in two places, and POSIX filenames may
contain `<`, `!`, `-`, `>`; a file named `<!-- jittest-report -->.py` injects a
second marker. And under `-O` the `assert` is stripped, at which point Defect 31
returns verbatim. **A security invariant must not live in an `assert`.**

### Defect 71 (SEVERE) — no secret redaction before publishing, and `_untrusted` only neutralises the marker

`failure_excerpt`, `repro_command` and `test_code` go straight into a public
comment with no scan for `ghs_`, `ghp_`, `github_pat_`, `sk-`, or high-entropy
strings. Actions log masking does not apply to comment bodies.

`summary`, `reviewer_question`, `badge` and `severity` render **unfenced**, and
`_untrusted` escapes only `MARKER`, `<!--` and `-->`. `</sub>`, `</details>`,
markdown links and images all pass — so an attacker-authored summary can close the
toggle early and publish a tracking pixel and a phishing link **with the
repository bot's authority behind it.** Note that `_fence` already solves the
fence-widening problem correctly; `prompts.py` and the inline fields do not reuse
it.

---

## What the auditors could confirm is sound

Credit where it is due — these were probed and held:

- **Head-side `PASS` → discard.** Unambiguous, and errs only toward
  over-discarding, which is the safe direction.
- **Latent-mode routing for a genuine fails-on-both.** Does not contaminate
  `report.findings` or `has_regression`.
- **`Worktree.__enter__` error propagation.** The `RuntimeError` on clone failure
  genuinely propagates rather than degrading to a green run — the one place in the
  oracle path where empty-vs-error is handled correctly.
- **The gate cannot be passed with a missing, empty or unparseable artifact,** and
  it runs after upload and unmasked, so the artifact survives while the job turns
  red. This is correct as far as it goes; Defects 51–53 are about a *well-formed*
  artifact containing no evidence.

---

## Fix order

The register is not the work queue. This is:

1. **Defects 32, 33, 34** — until "passes on base" means a test actually ran and
   passed against verified base code, every other number is downstream of a
   broken oracle. Nothing else matters before this.
2. **Defect 47** — execute BugsInPy's ground-truth test. Store `base_passed` /
   `head_failed` / `test_executed` per bug. Define `caught` as oracle-verified,
   never as `should_report`.
3. **Defects 48, 50** — make the denominator `bugs_attempted`, require a minimum
   sample and a maximum failure ratio, and give `false_positives.py` a gate at
   least as strong as `assert_measured.py`.
4. **Defects 43, 45, 49** — per-bug non-empty-diff assertion, and a `Report`
   status field that distinguishes "found nothing" from "never ran."
5. **Defects 64, 66** — before this is pointed at any public repository. The
   correct fix is not more denylist entries; it is a container with no network and
   no secrets, plus fenced-and-labelled untrusted input.
6. Everything else.

Defects 32–61 are correctness. Defects 62–71 are a precondition for the Week 5
design-partner step, because that step points this tool at repositories whose PRs
are opened by strangers.
