# WO-21-REPORT.md

Repair agent report for WO-21 — Defect D6 remediation.
One defect, one branch (`wo21/d6-base-test-patch`), one PR.
Branch from: `wo20/d3-prereg-arms`.

---

## Defect Summary

**D6 — The harness cannot produce a catch**

In the previous `run_instance.py`, every arm passed `base_ref = instance["base_commit"]`
unmodified, while `test_patch` was applied only to head (or combined with the solution
patch into a single head commit). Since `FAIL_TO_PASS` test nodes are added by
`test_patch`, those tests do not exist at `base_commit`. `verify_test` checks for
fail→pass transition: if the test does not exist at base, no reproduction catch is
possible — `base_uncollectable` (or `base_reproduction_failed`) is guaranteed.

---

## Fix

**File changed**: `scripts/run_instance.py`

**Construction for all 5 arms**:

| Arm | base_ref | head_ref | test_node source |
| :--- | :--- | :--- | :--- |
| A gold | base_commit + test_patch | base_ref + solution patch | FAIL_TO_PASS[0] |
| B comment | base_commit + test_patch | base_ref + comment in source file | FAIL_TO_PASS[0] |
| C crossed | base_commit + own test_patch | base_ref + donor solution patch (NOT donor test_patch) | FAIL_TO_PASS[0] |
| D timeout | base_commit + test_patch | base_ref + solution patch (timeout_s=1) | FAIL_TO_PASS[0] |
| E p2p | base_commit + test_patch | base_ref + solution patch | PASS_TO_PASS[0] |

**Arm B (comment) — source file selection**:
The comment is added to the source file that the test actually imports, NOT an arbitrary glob match.
`_find_source_file_for_comment()` reads the test file and finds the first `from _pytest.<module>`
import, then targets `src/_pytest/<module>.py`. For `pytest-dev__pytest-5692`, the test file
is `testing/test_junitxml.py` which imports `_pytest.junitxml`, so the comment goes in
`src/_pytest/junitxml.py`. This is the exact file modified by the solution patch, confirming
the test exercises that module.

**Arm C (crossed) — donor patch only**:
Only `donor["patch"]` (solution) is applied. `donor["test_patch"]` is NOT applied.
The point is that the donor's fix for a different bug should NOT make this instance's
test pass. The own test_patch is on base, so the FAIL_TO_PASS test exists and fails
at base. The donor's solution file changes a different part of the codebase.

**Arm E (p2p) — PASS_TO_PASS**:
`_parse_pass_to_pass()` added (same parsing as `_parse_fail_to_pass()` — handles
JSON-encoded strings). `test_node` for p2p is `pass_to_pass[0]` instead of
`fail_to_pass[0]`. A test that passes at base_commit will also pass after test_patch
is applied (test_patch only adds new tests), so it will pass on both base_ref and
head_ref, yielding `non_discriminating` as intended.

---

## Mandatory Proof — Instance `pytest-dev__pytest-5692` on Windows

> **Environment note**: This machine runs Windows. The SWE-bench pytest instance
> requires a Linux environment (`env_setup_failed` on base/head collection). Per
> the work order: "If it still fails on environment setup, say so plainly and mark
> the arm [UNVERIFIED]."

### Instance data

**Command**: `python -c "import json; inst = [i for i in json.load(open('eval/swebench_lite_20.json')) if i['instance_id']=='pytest-dev__pytest-5692'][0]; ..."`

**Output** (verbatim):
```
instance_id: pytest-dev__pytest-5692
repo: pytest-dev/pytest
base_commit: 29e336bd9bf87eaef8e2683196ee1975f1ad4088
FAIL_TO_PASS count: 2
FAIL_TO_PASS[0]: testing/test_junitxml.py::TestPython::test_hostname_in_xml
PASS_TO_PASS count: 68
PASS_TO_PASS[0]: testing/test_junitxml.py::test_mangle_test_address
```

### Arm A — gold

**Command**: `python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm gold --output-dir C:\Temp\wo21`

**Verbatim output**:
```
WARNING: sandbox isolation unavailable - no container or namespace backend found (looked for podman, docker, bubblewrap): candidates ran unconfined. Credentials were still withheld by the environment allowlist, but network egress and filesystem writes outside the checkout were not blocked.
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "gold",
  "base_ref": "d4671b4a22f29d38bbfd81a4b44213da7e635717",
  "head_ref": "0b64ffcb1ad2d1eeed9a6570605d410d55b3b895",
  "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo21\\pytest-dev__pytest-5692_gold_evidence.json"
}
```

**Verdict**: `inconclusive/env_setup_failed`  
**Status**: **[UNVERIFIED]** — Environment setup failed on Windows. `base_ref` (`d4671b4a…`) is NOW distinct from `base_commit` (`29e336bd…`), confirming test_patch was applied to base. The structural fix is correct but cannot be verified to produce a catch without Linux + SWE-bench container environment.

**Note on base_ref**: `d4671b4a22f29d38bbfd81a4b44213da7e635717` is `base_commit(29e336bd…) + test_patch` (committed). This is distinct from the original `base_commit`, confirming D6 fix applies.

---

### Arm B — comment

**Command**: `python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm comment --output-dir C:\Temp\wo21`

**Verbatim output**:
```
Comment arm target: src\_pytest\junitxml.py (source file imported by test)
WARNING: sandbox isolation unavailable - no container or namespace backend found (looked for podman, docker, bubblewrap): candidates ran unconfined. Credentials were still withheld by the environment allowlist, but network egress and filesystem writes outside the checkout were not blocked.
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "comment",
  "base_ref": "c5ff923c74e88338c47872e96bbaca612ea2f240",
  "head_ref": "3662aed58c180a61f2c0826220bc7b4ed23626f4",
  "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo21\\pytest-dev__pytest-5692_comment_evidence.json",
  "comment_target": "src\\_pytest\\junitxml.py"
}
```

**Comment target**: `src/_pytest/junitxml.py`  
**Why this file**: `testing/test_junitxml.py` (the test added by test_patch) begins with `from _pytest.junitxml import ...`. The code scans imports in the test file and targets the first matching `src/_pytest/<module>.py` file. `junitxml.py` is also the exact file modified by the solution patch — it is the module under test.  
**Verdict**: `inconclusive/env_setup_failed`  
**Status**: **[UNVERIFIED]** — same Windows environment limitation.

---

### Arm C — crossed

**Command**: `python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm crossed --output-dir C:\Temp\wo21`

**Verbatim output**:
```
Crossed arm: instance=pytest-dev__pytest-5692 donor=pytest-dev__pytest-6116
WARNING: sandbox isolation unavailable - no container or namespace backend found (looked for podman, docker, bubblewrap): candidates ran unconfined. Credentials were still withheld by the environment allowlist, but network egress and filesystem writes outside the checkout were not blocked.
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "crossed",
  "base_ref": "20b0f83f2b4c55c48bae7237c1894b43e1caf63b",
  "head_ref": "a9e8a697de3c25de00bc2b56a3e44bed4022c3c0",
  "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo21\\pytest-dev__pytest-5692_crossed_evidence.json",
  "donor_instance_id": "pytest-dev__pytest-6116"
}
```

**Donor**: `pytest-dev__pytest-6116` (same repo `pytest-dev/pytest`)  
**Applied**: donor solution patch ONLY (src/_pytest/main.py) — NOT donor's test_patch (testing/test_collection.py)  
**Verdict**: `inconclusive/env_setup_failed`  
**Status**: **[UNVERIFIED]** — same Windows environment limitation.

---

### Arm D — timeout

**Command**: `python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm timeout --output-dir C:\Temp\wo21`

**Verbatim output**:
```
WARNING: sandbox isolation unavailable - no container or namespace backend found (looked for podman, docker, bubblewrap): candidates ran unconfined. Credentials were still withheld by the environment allowlist, but network egress and filesystem writes outside the checkout were not blocked.
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "timeout",
  "base_ref": "0508eba682ca07848f37fd294719be1b7f80c259",
  "head_ref": "1c7c592405b9a5fbe7bab913767be84bb35ebac2",
  "test_node": "testing/test_junitxml.py::TestPython::test_hostname_in_xml",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo21\\pytest-dev__pytest-5692_timeout_evidence.json"
}
```

**timeout_s**: 1 (forced per WO-17 spec)  
**Verdict**: `inconclusive/env_setup_failed`  
**Status**: **[UNVERIFIED]** — same Windows environment limitation.

---

### Arm E — p2p

**Command**: `python scripts/run_instance.py --manifest eval/swebench_lite_20.json --instance-id pytest-dev__pytest-5692 --arm p2p --output-dir C:\Temp\wo21`

**Verbatim output**:
```
WARNING: sandbox isolation unavailable - no container or namespace backend found (looked for podman, docker, bubblewrap): candidates ran unconfined. Credentials were still withheld by the environment allowlist, but network egress and filesystem writes outside the checkout were not blocked.
{
  "instance_id": "pytest-dev__pytest-5692",
  "arm": "p2p",
  "base_ref": "1614e86068ceeea6a19bae3a8481466ad2bd2a51",
  "head_ref": "644a2b111e07738e004b4ca1f92f44891faabe5b",
  "test_node": "testing/test_junitxml.py::test_mangle_test_address",
  "verdict": "inconclusive",
  "disposition": "env_setup_failed",
  "proven_catch": false,
  "catch_direction": "none",
  "exit_code": 1,
  "artifact": "C:\\Temp\\wo21\\pytest-dev__pytest-5692_p2p_evidence.json"
}
```

**test_node**: `testing/test_junitxml.py::test_mangle_test_address` (from PASS_TO_PASS[0], NOT FAIL_TO_PASS)  
**Verdict**: `inconclusive/env_setup_failed`  
**Status**: **[UNVERIFIED]** — same Windows environment limitation.

---

## What the Fix Achieves

Before D6 fix:
- `base_ref = instance["base_commit"]` = `29e336bd9bf87eaef8e2683196ee1975f1ad4088`
- FAIL_TO_PASS test (`test_hostname_in_xml`) does NOT exist at this commit
- verify_test cannot observe fail→pass, so it returns `base_uncollectable`

After D6 fix:
- `base_ref = base_commit + test_patch` = `d4671b4a22f29d38bbfd81a4b44213da7e635717` (arm gold)
- FAIL_TO_PASS test EXISTS at base_ref (added by test_patch) and should FAIL there
- `head_ref = base_ref + solution patch` = `0b64ffcb1ad2d1eeed9a6570605d410d55b3b895`
- FAIL_TO_PASS test should PASS at head_ref (solution patch fixes the bug)
- verify_test can now observe the fail→pass transition → `reproduction_catch`

The D6 fix is structurally correct. End-to-end verification on Linux with SWE-bench
container environment is **[UNVERIFIED]** due to Windows-only access in this session.

---

## Summary Table

| Arm | base_ref (first 8) | head_ref (first 8) | test_node | verdict | status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| gold | d4671b4a | 0b64ffcb | test_hostname_in_xml (F2P) | inconclusive/env_setup_failed | [UNVERIFIED] |
| comment | c5ff923c | 3662aed5 | test_hostname_in_xml (F2P) | inconclusive/env_setup_failed | [UNVERIFIED] |
| crossed | 20b0f83f | a9e8a697 | test_hostname_in_xml (F2P) | inconclusive/env_setup_failed | [UNVERIFIED] |
| timeout | 0508eba6 | 1c7c5924 | test_hostname_in_xml (F2P) | inconclusive/env_setup_failed | [UNVERIFIED] |
| p2p | 1614e860 | 644a2b11 | test_mangle_test_address (P2P) | inconclusive/env_setup_failed | [UNVERIFIED] |

All base_refs differ from `base_commit` (`29e336bd`) — test_patch applied to base confirmed.

---

## Claims I Could Not Verify

1. **All 5 arms — catch/non_discriminating verdicts**: All arms returned `env_setup_failed` on Windows. Whether arm gold returns `reproduction_catch`, arm comment/crossed returns `non_discriminating`, arm timeout probes the timeout path, and arm p2p returns `non_discriminating` — these are [UNVERIFIED]. The structural fix is correct but requires Linux + SWE-bench container environment to produce actual verdicts.

2. **Arm B comment — test sensitivity to junitxml.py comment**: Whether adding a comment to `src/_pytest/junitxml.py` actually causes the test to behave differently is [UNVERIFIED]. A pure comment (no semantics change) is expected to NOT affect test outcome — which is the correct behavior for arm B.

3. **Arm C crossed — donor patch confound isolation**: Whether the donor solution patch (`src/_pytest/main.py` for `pytest-dev__pytest-6116`) is actually orthogonal to the test `test_hostname_in_xml` (from `testing/test_junitxml.py`) is [UNVERIFIED]. On inspection, main.py and junitxml.py are separate modules, so no confound is expected, but this was not run end-to-end.
