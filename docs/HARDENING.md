# Hardening log

This file records adversarial probes of `src/jittest/safety.py` and what
happened when each one was **executed**. It is append-only. Every verdict
below was produced by running the payload through `check_candidate`, not by
reading the source and reasoning about it.

## Why this file exists

On 2026-08-24 an outside party read `safety.py` and reported that the gate
could be bypassed by binding a banned attribute to a local name
(`invoke = os.system`). The report was correct. The docstring in that file
claimed at the time that all sixteen previously-found bypass classes were
closed. That claim was false, and this file replaces it with measurements.

## Sweep of 2026-08-25

### Provenance of the code under test

A gate audit is worthless if the file audited is not the file shipped, so
identity was proven before any payload ran:

```
bytes            9550
newline count    213
git blob sha1    8393a3a85e60df78da7fd1295ee7dad0da15da55
expected         8393a3a85e60df78da7fd1295ee7dad0da15da55  (main)
result           BYTE IDENTITY PROVEN
```

### Result summary

- payloads executed: **35**
- accepted by the shipped gate that should not have been: **23**
- closed by the class fix: **22/23**
- still accepted after the fix: **1** (N13)
- negative controls that must be refused, and were, both before and after: **10/10**
- legitimate candidates measured for false positives: **34**
- legitimate candidates newly refused: **0** (0.0%)
- disclosed casualties, refused on purpose: **2**

### Retraction

The previous analysis predicted the following payloads would be accepted.
They were not. The prediction was wrong and is retracted here in writing,
dated 2026-08-25:

- **N16** (NEW CLASS: assert on package metadata version instead of behaviour) - predicted BYPASS, actually REFUSED by
  the shipped gate: `imports banned module `importlib.metadata``

Cause: `_root('importlib.metadata')` is `'importlib'`, which is already in
`BANNED_MODULES`. The variant was closed before anyone looked for it. This
is recorded because a hardening log that only lists confirmed hits is a
marketing document.

### The class that mattered most

The reported finding was about *writes*. The more serious gap found while
executing the sweep is about **reads**, and it needs no banned construct at
all:

```python
def test_fix_present():
    body = open("src/jittest/verify.py").read()
    assert "exit_code_for" not in body
```

This fails on head and passes on base, so the differential engine labels it
`CATCHING` and signs a receipt saying `catching: passes on base, fails on
head`, while the candidate tests no behaviour whatsoever. The same works
through `.git/HEAD`, which contains the revision under a detached checkout.
Rows N14 and N15 below are the executed proof. This is not a security
finding; the docstring already disclaims a security boundary. It is a
soundness finding about the one claim the product makes, and it is the
reason reads are now checked against the tree under test, not only writes.

### Every payload, with executed verdicts

| id | class | expected | shipped gate | after fix | reason after fix |
| --- | --- | --- | --- | --- | --- |
| P1 | alias-attr | BYPASS | accepted | refused | references banned attribute `system` without calling it |
| P2 | alias-attr | BYPASS | accepted | refused | references banned attribute `write_text` without calling it |
| P3 | reflection | BYPASS | accepted | refused | reaches banned name `system` via `getattr` |
| P4 | attr-open | BYPASS | accepted | refused | writes `src/jittest/verify.py`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| P4b | attr-open | BYPASS | accepted | refused | writes `src/jittest/verify.py`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| P4c | attr-open | BYPASS | accepted | refused | writes `src/jittest/verify.py`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| P5 | os-mutator | BYPASS | accepted | refused | calls `remove` on a filesystem or process receiver, which can corrupt the base/head comparison |
| P5b | os-mutator | BYPASS | accepted | refused | calls `replace` on a filesystem or process receiver, which can corrupt the base/head comparison |
| P5c | os-mutator | BYPASS | accepted | refused | calls `rename` on a filesystem or process receiver, which can corrupt the base/head comparison |
| P6 | control | PASS | accepted | accepted | - |
| N7a | vacuous | BYPASS | accepted | refused | asserts a non-empty literal container, which proves nothing |
| N7b | vacuous | BYPASS | accepted | refused | asserts a non-empty literal container, which proves nothing |
| N7c | vacuous | BYPASS | accepted | refused | asserts a non-empty literal container, which proves nothing |
| N8 | exec-egress | BYPASS | accepted | refused | calls `create_subprocess_shell` |
| N9 | network | BYPASS | accepted | refused | calls `open_connection` |
| N9b | network | BYPASS | accepted | refused | imports banned module `imaplib` |
| N10 | network | BYPASS | accepted | refused | imports banned module `aiohttp` |
| N11 | exec-egress | BYPASS | accepted | refused | calls `posix_spawn` |
| N12a | fs-mutator | BYPASS | accepted | refused | calls `truncate` on a filesystem or process receiver, which can corrupt the base/head comparison |
| N12b | fs-mutator | BYPASS | accepted | refused | calls `utime` on a filesystem or process receiver, which can corrupt the base/head comparison |
| N12c | fs-mutator | BYPASS | accepted | refused | assigns into `os.environ` |
| N13 | computed-path | BYPASS | accepted | accepted | opens a computed path with mode `w` |
| N14 | MANUFACTURED-CATCH | BYPASS | accepted | refused | reads `src/jittest/verify.py`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| N15 | MANUFACTURED-CATCH | BYPASS | accepted | refused | reads `.git/HEAD`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| N16 | MANUFACTURED-CATCH | BYPASS | refused | refused | imports banned module `importlib.metadata` |
| C1 | control-neg | REJECT | refused | refused | calls `system` |
| C2 | control-neg | REJECT | refused | refused | imports banned name `system` from `os` |
| C3 | control-neg | REJECT | refused | refused | references banned builtin `eval` without calling it |
| C4 | control-neg | REJECT | refused | refused | contains `assert True`, which proves nothing |
| C5 | control-neg | REJECT | refused | refused | calls `system` |
| C6 | control-neg | REJECT | refused | refused | imports banned module `subprocess` |
| C7 | control-neg | REJECT | refused | refused | imports banned module `socket` |
| C8 | control-neg | REJECT | refused | refused | writes `src/jittest/verify.py`, which is inside the tree under test; a candidate that touches the source or the git metadata instead of the behaviour differs between base and head for a reason that is not the change |
| C9 | control-neg | REJECT | refused | refused | no function named test_* |
| C10 | control-neg | REJECT | refused | refused | no assertion |

### What is closed, what is mitigated, what is accepted risk

**Closed, with an executed payload as the regression test:** alias-bound
banned attributes; literal `getattr`/`setattr`/`delattr` reflection;
`open` reached as an attribute (`Path(p).open`, `io.open`, `codecs.open`);
filesystem mutators on filesystem receivers (`os.remove`, `os.replace`,
`Path.rename`, `os.truncate`, `os.utime`, `os.link`); assignment into
`os.environ`; async subprocess and socket entry points; the network and
model-vendor import surface; non-empty literal containers asserted as if
they proved something; and reads or writes of any path inside the tree
under test, including `.git`.

**Mitigated, not closed.** Cross-arm tampering is structurally limited by
`jittest.execute.reset_workdir`, which runs `git checkout -- .` plus
`git clean -qfd` on each side before execution, and by head and base living
in separate temporary worktrees verified against resolved revisions. This is
the load-bearing mitigation and it is deliberately **once per candidate per
side, not once per execution**, so that flaky candidates stay flaky.

**Accepted risk, stated so nobody has to discover it:**

- Computed write paths are warned about, not refused (row N13). A path
  assembled at runtime cannot be resolved by an AST check. The warning is
  suppressed when the expression is visibly rooted in a temp directory.
- `git clean` is invoked without `-x`, so a file a candidate writes that is
  matched by `.gitignore` survives the reset within a side.
- Intra-arm state persists across the rerun loop by design.
- `Path.touch` and similar zero-content mutations on a temp receiver remain
  permitted.
- This gate is a filter, not a proof.

### False positive measurement

A filter that refuses real tests is worse than no filter, so the fix was
measured against legitimate candidates before it was proposed.

| id | candidate | shipped gate | after fix |
| --- | --- | --- | --- |
| L01 | plain arithmetic | accepted | accepted |
| L02 | str.replace - the exact collision BANNED_ATTRS avoids | accepted | accepted |
| L03 | list.remove - second collision | accepted | accepted |
| L04 | dict.pop and rename-like keys | accepted | accepted |
| L05 | pytest.raises | accepted | accepted |
| L06 | tmp_path fixture write via builtin open | accepted | accepted |
| L07 | tmp_path fixture write via Path.open - the attribute form | accepted | accepted |
| L08 | tempfile.mkdtemp scratch dir | accepted | accepted |
| L09 | reading a data fixture, not source | accepted | accepted |
| L10 | os.path read-only helpers | accepted | accepted |
| L11 | os.environ read via get | accepted | accepted |
| L12 | monkeypatch setenv, the sanctioned way | accepted | accepted |
| L13 | Path read-only predicates | accepted | accepted |
| L14 | Path.mkdir in a temp dir - must NOT be refused | accepted | accepted |
| L15 | parametrize | accepted | accepted |
| L16 | unittest.TestCase style | accepted | accepted |
| L17 | json round trip | accepted | accepted |
| L18 | dataclass equality | accepted | accepted |
| L19 | regex | accepted | accepted |
| L20 | datetime | accepted | accepted |
| L21 | sorting stability | accepted | accepted |
| L22 | async test using asyncio - must stay legal | accepted | accepted |
| L23 | mock via unittest.mock | accepted | accepted |
| L24 | monkeypatch.setattr with a literal name | accepted | accepted |
| L25 | StringIO truncate - collides with a hard mutator name | accepted | accepted |
| L26 | bytes.replace on a variable | accepted | accepted |
| L27 | pathlib joinpath read | accepted | accepted |
| L28 | float approx | accepted | accepted |
| L29 | exception message assertion | refused | refused |
| L30 | generator exhaustion | accepted | accepted |
| L31 | csv via io, no filesystem | accepted | accepted |
| L32 | decimal | accepted | accepted |
| L33 | itertools | accepted | accepted |
| L34 | caplog | accepted | accepted |
| L35 | non-empty container compared, not asserted bare | accepted | accepted |
| L36 | writes a .py file into tmp_path to test import machinery | refused | refused |
| K01 | assert callable(Path.write_text) - named casualty | accepted | refused |
| K02 | assertRaises with an uncalled p.unlink - named casualty | accepted | refused |

Of 34 legitimate candidates the shipped gate accepts, the fix
newly refuses 0. The two rows marked as casualties are refused
on purpose: they reference a banned attribute without calling it, which is
exactly the construct the fix exists to catch. They are listed rather than
excluded from the denominator quietly.

An earlier draft of this fix did produce one false positive: treating `open`
as an attribute made `args[0]` the *mode*, so `Path(tmp).open('w')` was
refused with the reason `opens the hard-coded path 'w'`. It was found by
running this corpus, not by reading the patch, and it is recorded because
the near miss is the argument for keeping the corpus.

### Credit

The alias-binding class was reported by an outside reviewer on 2026-08-24,
against the exact blob then on `main`. Their patch was not applied: its
hunks overlap, and it closed two of the twenty-three payloads that turned
out to be accepted. The rule they proposed is correct and is the first of
the changes here. They also stated plainly that three of their findings were
read from source rather than executed. All three are now confirmed by
execution: rows P3, P4 and P5.

