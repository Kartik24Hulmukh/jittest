"""The differential oracle. This is the load-bearing file in the repository.

Every other component is replaceable. This one is the product:

    keep a candidate test  IFF  it FAILS on head
                            AND the failure reproduces across reruns
                            AND it PASSES on base

No model is consulted here and no model can overrule the result. A test that
passes on head is a hardening test - useful to somebody, useless to a reviewer
asking "did I break something?" - and is discarded. A test that fails on both
sides found a pre-existing fault, which is interesting but is not this PR's
fault, so it is reported only in latent mode.

That asymmetry is why jittest can be quiet. Most tools cannot be quiet, because
they have no mechanical way to know when they have nothing to say.

One warning, learned the hard way (Defect 32). "PASSES on base" is half of the
rule above, and an exit code cannot establish it. Both runners exit 0 when they
skipped everything they collected, so success must be proved by positive
evidence that a test really executed. See Outcome.NOTRUN.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "Outcome", "RunResult", "Verdict", "Worktree", "run_test",
    "differential_check", "detect_runner", "CANDIDATE_PREFIX",
]

CANDIDATE_PREFIX = "test_jittest_candidate_"
_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)
TAIL_LIMIT = 2500

# A <testcase> carrying any of these did not execute and pass.
_NONPASSING_TAGS = frozenset({"skipped", "failure", "error"})


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"       # could not be collected or imported
    TIMEOUT = "timeout"
    NOTRUN = "notrun"     # exited cleanly, but no test actually executed


@dataclass
class RunResult:
    outcome: Outcome
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def tail(self) -> str:
        # This was declared as a property taking a `limit` argument, which is
        # unreachable: a property is called with no arguments, so the parameter
        # could never be supplied by any caller.
        combined = (self.stdout + "\n" + self.stderr).strip()
        return combined[-TAIL_LIMIT:]


@dataclass
class Verdict:
    is_catching: bool
    reason: str
    latent: bool = False
    failure_excerpt: str = ""
    head_outcome: Outcome | None = None
    base_outcome: Outcome | None = None


def detect_runner() -> list[str]:
    """Prefer the project's own pytest. Fall back to the bundled mini-runner."""
    if os.getenv("JITTEST_FORCE_MINIRUNNER") == "1":
        return [sys.executable, "-m", "jittest._minirunner"]
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"], capture_output=True, text=True, errors="replace",
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return [sys.executable, "-m", "jittest._minirunner"]


class Worktree:
    """A detached checkout of one revision, created once and reused.

    Creating a worktree per candidate test was the single biggest cost in the
    first version. Creating two per pull request instead makes three executions
    per candidate affordable, which is what buys the flakiness rerun.
    """

    def __init__(self, repo: Path | str, rev: str) -> None:
        self.repo = Path(repo).resolve()
        self.rev = rev
        self.path = Path(tempfile.mkdtemp(prefix="jittest-wt-"))
        self._added = False

    def __enter__(self) -> Path:
        added = subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "--detach",
             "--force", str(self.path), self.rev],
            capture_output=True, text=True, errors="replace",
        )
        if added.returncode == 0:
            self._added = True
            return self.path

        # Worktrees can be refused (already checked out, older git, odd CI
        # layouts). A shared clone is slower but always works.
        shutil.rmtree(self.path, ignore_errors=True)
        cloned = subprocess.run(
            ["git", "clone", "--quiet", "--shared", "--no-checkout",
             str(self.repo), str(self.path)],
            capture_output=True, text=True, errors="replace",
        )
        if cloned.returncode != 0:
            raise RuntimeError(f"cannot materialise {self.rev}: {cloned.stderr.strip()}")
        subprocess.run(
            ["git", "-C", str(self.path), "checkout", "--quiet", "--detach", self.rev],
            capture_output=True, text=True, errors="replace", check=True,
        )
        return self.path

    def __exit__(self, *exc: object) -> None:
        if self._added:
            subprocess.run(
                ["git", "-C", str(self.repo), "worktree", "remove", "--force",
                 str(self.path)],
                capture_output=True, text=True, errors="replace",
            )
        shutil.rmtree(self.path, ignore_errors=True)


def _env_for(workdir: Path) -> dict:
    env = dict(os.environ)
    parts = [str(workdir), str(workdir / "src"), _PACKAGE_ROOT]
    existing = env.get("PYTHONPATH")
    if existing:
        parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"          # kill one source of ordering flakiness
    env["JITTEST_CHILD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _passed_from_junit(report: Path) -> int | None:
    """Count testcases that executed and did not skip, fail or error.

    Returns None when the report is absent or unparseable. The caller must
    treat None as "unknown", never as "passed": the whole point of reading this
    file is to refuse to infer success from an exit code.
    """
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None
    passed = 0
    for case in root.iter("testcase"):
        if any(child.tag in _NONPASSING_TAGS for child in case):
            continue
        passed += 1
    return passed


def run_test(workdir: Path, test_code: str, timeout_s: int = 120) -> RunResult:
    """Write the candidate into the checkout, run it, then remove it."""
    workdir = Path(workdir)
    token = uuid.uuid4().hex[:8]
    candidate = workdir / f"{CANDIDATE_PREFIX}{token}.py"
    candidate.write_text(test_code, encoding="utf-8")
    runner = detect_runner()
    uses_pytest = "pytest" in runner
    report = workdir / f".jittest-junit-{token}.xml"
    command = [*runner, str(candidate)]
    if uses_pytest:
        command.append(f"--junitxml={report}")
    try:
        proc = subprocess.run(
            command,
            cwd=str(workdir), env=_env_for(workdir),
            capture_output=True, text=True, errors="replace", timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return RunResult(Outcome.TIMEOUT, -1, "", f"timed out after {timeout_s}s")
    finally:
        candidate.unlink(missing_ok=True)

    code = proc.returncode
    try:
        if code == 0:
            # Defect 32. Exit 0 does NOT mean a test passed. pytest exits 0 when
            # every test was SKIPPED, and the mini-runner did the same for every
            # fixture-using test. "PASSES on base" is the load-bearing half of
            # the oracle, so it now requires positive evidence that at least one
            # test really executed and really passed.
            outcome = Outcome.PASS
            if uses_pytest:
                passed = _passed_from_junit(report)
                if not passed:          # None (unknown) or 0 (nothing passed)
                    outcome = Outcome.NOTRUN
        elif code == 1:
            outcome = Outcome.FAIL
        elif code == 5:
            # Both runners use 5 for "no tests collected", and the mini-runner
            # now also uses it for "collected, but every one was skipped".
            outcome = Outcome.NOTRUN
        else:
            # pytest: 2 usage/collection, 3 internal, 4 usage.
            outcome = Outcome.ERROR
    finally:
        report.unlink(missing_ok=True)
    return RunResult(outcome, code, proc.stdout, proc.stderr)


def differential_check(
    repo: Path | str,
    base: str,
    head: str,
    test_code: str,
    timeout_s: int = 120,
    reruns: int = 2,
    head_workdir: Path | None = None,
    base_workdir: Path | None = None,
) -> Verdict:
    """Run the candidate on head, then base, and decide. No model involved."""
    repo = Path(repo).resolve()
    owns_head = head_workdir is None
    owns_base = base_workdir is None
    head_ctx = Worktree(repo, head) if owns_head else None
    base_ctx = Worktree(repo, base) if owns_base else None

    try:
        head_dir = head_ctx.__enter__() if head_ctx else Path(head_workdir)  # type: ignore[arg-type]

        first = run_test(head_dir, test_code, timeout_s)
        if first.outcome is Outcome.ERROR:
            return Verdict(False, "discarded: test could not be collected on head",
                           failure_excerpt=first.tail, head_outcome=first.outcome)
        if first.outcome is Outcome.TIMEOUT:
            return Verdict(False, "discarded: timed out on head",
                           failure_excerpt=first.tail, head_outcome=first.outcome)
        if first.outcome is Outcome.NOTRUN:
            return Verdict(False, "discarded: no test actually executed on head "
                                  "(every collected test was skipped, or none "
                                  "was collected)",
                           failure_excerpt=first.tail, head_outcome=first.outcome)
        if first.outcome is Outcome.PASS:
            return Verdict(False, "discarded: passes on head, so it is a hardening "
                                  "test rather than a catching test",
                           head_outcome=first.outcome)

        # It failed on head. Prove the failure is not luck before we spend a
        # base checkout on it, and long before we spend a reviewer's attention.
        for _ in range(max(0, reruns - 1)):
            again = run_test(head_dir, test_code, timeout_s)
            if again.outcome is not Outcome.FAIL:
                return Verdict(False, "discarded: non-deterministic across reruns "
                                      "on head (flaky)",
                               failure_excerpt=first.tail, head_outcome=first.outcome)

        base_dir = base_ctx.__enter__() if base_ctx else Path(base_workdir)  # type: ignore[arg-type]
        on_base = run_test(base_dir, test_code, timeout_s)

        if on_base.outcome is Outcome.PASS:
            return Verdict(True, "catching: passes on base, fails on head",
                           failure_excerpt=first.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome)
        if on_base.outcome is Outcome.FAIL:
            return Verdict(False, "discarded: fails on base too, so the fault is "
                                  "pre-existing rather than caused by this change",
                           latent=True, failure_excerpt=first.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome)
        if on_base.outcome is Outcome.NOTRUN:
            # The dangerous one. Previously this returned exit code 0, was read
            # as PASS, and produced "catching: passes on base, fails on head"
            # for a test that never ran on base at all - including when the
            # symbol under test did not yet exist on that revision.
            return Verdict(False, "discarded: no test executed on base, so "
                                  "'passes on base' cannot be established",
                           failure_excerpt=on_base.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome)
        return Verdict(False, "discarded: could not be collected on base, so no "
                              "comparison is possible",
                       failure_excerpt=on_base.tail,
                       head_outcome=first.outcome, base_outcome=on_base.outcome)
    finally:
        if base_ctx:
            base_ctx.__exit__(None, None, None)
        if head_ctx:
            head_ctx.__exit__(None, None, None)
