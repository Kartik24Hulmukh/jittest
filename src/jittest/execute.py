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

A second warning (Defects 33-35). The rule is also a claim about two specific
commits. If a checkout is not on the revision it is supposed to be on, or still
contains what the previous candidate left behind, then the verdict is a
confident sentence about nothing identifiable. Both are now checked rather than
assumed. See resolve_revision, verify_workdir and reset_workdir.

A third warning (Defects 36-40). What happened to a candidate is stated, not
described. The reason string is for humans; Disposition, FailureKind and the
recorded per-execution outcomes are what other code is allowed to read.
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
    "resolve_revision", "worktree_revision", "verify_workdir",
    "reset_workdir", "RevisionMismatch", "Disposition", "FailureKind",
]

CANDIDATE_PREFIX = "test_jittest_candidate_"
_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)
TAIL_LIMIT = 2500

# A <testcase> carrying any of these did not execute and pass.
_NONPASSING_TAGS = frozenset({"skipped", "failure", "error"})


class Disposition(StrEnum):
    """Why a candidate ended where it did. Defect 38.

    The pipeline used to recover this by searching the verdict's English reason
    string for substrings like "could not be collected". That made prose a
    machine interface: rewording a sentence silently relabelled telemetry, and
    several genuinely different endings collapsed onto the same label because no
    substring distinguished them. The oracle now states the disposition
    directly, and the reason string goes back to being for humans only.
    """
    HEAD_UNCOLLECTABLE = "head_uncollectable"
    HEAD_TIMEOUT = "head_timeout"
    HEAD_NOTRUN = "head_notrun"
    HEAD_PASSED = "head_passed"
    HEAD_FLAKY = "head_flaky"
    HEAD_FAILED_BASE_FAILED_LATENT = "head_failed_base_failed_latent"
    BASE_NOTRUN = "base_notrun"
    BASE_UNCOLLECTABLE = "base_uncollectable"
    PROVENANCE_FAILED = "provenance_failed"
    CATCHING = "catching"


class FailureKind(StrEnum):
    """What kind of failure was observed. Defect 37.

    An assertion that fired is evidence about the code under test. An import
    error, a crash, or a runner problem is evidence about the candidate or the
    environment, and treating the two as one "fail" hid infrastructure breakage
    inside apparently meaningful results.
    """
    NONE = ""
    ASSERTION = "assertion"
    ERROR = "error"
    UNKNOWN = "unknown"


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
    failure_kind: FailureKind = FailureKind.NONE

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
    # Defect 33. Provenance: the resolved commit that each side was actually
    # executed against, read back from the checkout rather than assumed from
    # the revision string the caller passed in.
    head_sha: str = ""
    base_sha: str = ""
    # Defect 36/38/39. The disposition is stated, not parsed back out of prose,
    # and every execution that contributed to it is listed in order so a
    # reviewer can see how many runs were needed and what each one did.
    disposition: Disposition = Disposition.HEAD_FAILED_BASE_FAILED_LATENT
    head_runs: tuple[Outcome, ...] = ()
    base_runs: tuple[Outcome, ...] = ()
    failure_kind: FailureKind = FailureKind.NONE

    @property
    def head_run_count(self) -> int:
        return len(self.head_runs)

    @property
    def base_run_count(self) -> int:
        return len(self.base_runs)

    @property
    def rerun_agreement(self) -> bool:
        """True when every head execution reached the same outcome.

        Derived from recorded outcomes rather than from the wording of the
        reason string, which is what the pipeline used to do.
        """
        return len(set(self.head_runs)) <= 1


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


class RevisionMismatch(RuntimeError):
    """A checkout does not contain the revision it is supposed to contain.

    Defect 33/34. Every oracle result is a claim about two specific commits.
    If a worktree silently holds a different commit - a stale reuse, a failed
    checkout that still exited zero, a directory handed in by a caller - then
    "passes on base, fails on head" is a statement about nothing identifiable.
    Refusing to run is the only safe response.
    """


def resolve_revision(repo: Path | str, rev: str) -> str:
    """Resolve a revision string to a full commit SHA, or "" if unresolvable."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{rev}^{{commit}}"],
        capture_output=True, text=True, errors="replace",
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def worktree_revision(workdir: Path | str) -> str:
    """The commit a checkout is actually sitting on, or "" if unknown."""
    return resolve_revision(workdir, "HEAD")


def verify_workdir(workdir: Path | str, expected_sha: str, side: str) -> None:
    """Raise unless the checkout is on exactly the expected commit.

    An empty expectation is not an accusation: a revision that cannot be
    resolved cannot be checked, and inventing a mismatch there would discard
    valid work. The caller decides what an unresolvable revision means.
    """
    if not expected_sha:
        return
    actual = worktree_revision(workdir)
    if actual != expected_sha:
        raise RevisionMismatch(
            f"{side} checkout at {workdir} is on "
            f"{actual or 'an unreadable revision'}, not {expected_sha}")


def reset_workdir(workdir: Path | str) -> None:
    """Remove anything a previous candidate left behind.

    Defect 35. The base and head checkouts are created once and reused for every
    candidate, which is what makes three executions per candidate affordable.
    Reuse without cleaning means candidate N can be influenced by candidate
    N-1: a stray module, a written fixture file, stale bytecode shadowing the
    source under test. Tracked files are restored and jittest's own leftovers
    are deleted once per candidate per side, so each candidate starts from the
    revision and nothing else. Deliberately not once per execution: the rerun
    loop in differential_check needs cross-execution state to remain visible or
    a flaky candidate stops looking flaky.
    """
    workdir = Path(workdir)
    subprocess.run(
        ["git", "-C", str(workdir), "checkout", "--", "."],
        capture_output=True, text=True, errors="replace",
    )
    # Never -x: ignored build artefacts and virtualenvs are part of a usable
    # checkout, and removing them would break the runner rather than isolate it.
    subprocess.run(
        ["git", "-C", str(workdir), "clean", "-qfd",
         "-e", ".jittest*", "-e", "*.egg-info"],
        capture_output=True, text=True, errors="replace",
    )
    for leftover in workdir.glob(f"{CANDIDATE_PREFIX}*.py"):
        leftover.unlink(missing_ok=True)
    for leftover in workdir.glob(".jittest-junit-*.xml"):
        leftover.unlink(missing_ok=True)
    for cache in workdir.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


class Worktree:
    """A detached checkout of one revision, created once and reused.

    Creating a worktree per candidate test was the single biggest cost in the
    first version. Creating two per pull request instead makes three executions
    per candidate affordable, which is what buys the flakiness rerun.

    On entry the checkout is verified against the resolved commit. A checkout
    that exited zero without landing on the requested revision is a silent lie
    the oracle would otherwise repeat.
    """

    def __init__(self, repo: Path | str, rev: str) -> None:
        self.repo = Path(repo).resolve()
        self.rev = rev
        self.path = Path(tempfile.mkdtemp(prefix="jittest-wt-"))
        self._added = False
        self.expected_sha = ""

    def __enter__(self) -> Path:
        added = subprocess.run(
            ["git", "-C", str(self.repo), "worktree", "add", "--detach",
             "--force", str(self.path), self.rev],
            capture_output=True, text=True, errors="replace",
        )
        self.expected_sha = resolve_revision(self.repo, self.rev)
        if added.returncode == 0:
            self._added = True
            verify_workdir(self.path, self.expected_sha, self.rev)
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
        verify_workdir(self.path, self.expected_sha, self.rev)
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


def _failure_kind_from_junit(report: Path) -> FailureKind:
    """Distinguish an assertion that fired from a crash or a runner problem.

    pytest records assertions under <failure> and everything else - import
    errors, collection problems, unexpected exceptions - under <error>. When
    the report is missing or unreadable, say UNKNOWN rather than guessing.
    """
    try:
        root = ET.fromstring(report.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ET.ParseError):
        return FailureKind.UNKNOWN
    saw_failure = False
    for case in root.iter("testcase"):
        for child in case:
            if child.tag == "error":
                return FailureKind.ERROR
            if child.tag == "failure":
                saw_failure = True
    return FailureKind.ASSERTION if saw_failure else FailureKind.UNKNOWN


def _failure_kind_from_output(text: str) -> FailureKind:
    """Fallback for the mini-runner, which writes no junit report."""
    if "AssertionError" in text or " assert " in text:
        return FailureKind.ASSERTION
    if text.strip():
        return FailureKind.ERROR
    return FailureKind.UNKNOWN


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
        return RunResult(Outcome.TIMEOUT, -1, "", f"timed out after {timeout_s}s",
                         failure_kind=FailureKind.UNKNOWN)
    finally:
        candidate.unlink(missing_ok=True)

    code = proc.returncode
    kind = FailureKind.NONE
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
            # Defect 37. "It failed" is not enough: an assertion firing is
            # evidence about the code, a crash is evidence about the candidate.
            kind = (_failure_kind_from_junit(report) if uses_pytest
                    else _failure_kind_from_output(proc.stdout + proc.stderr))
        elif code == 5:
            # Both runners use 5 for "no tests collected", and the mini-runner
            # now also uses it for "collected, but every one was skipped".
            outcome = Outcome.NOTRUN
        else:
            # pytest: 2 usage/collection, 3 internal, 4 usage.
            outcome = Outcome.ERROR
            kind = FailureKind.ERROR
    finally:
        report.unlink(missing_ok=True)
    return RunResult(outcome, code, proc.stdout, proc.stderr, failure_kind=kind)


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

    # Defect 33/34. Every verdict below is a claim about two specific commits,
    # so both are resolved once here and every checkout is checked against them
    # before a candidate is executed in it. A caller-supplied directory is not
    # trusted to contain what its name suggests.
    head_sha = resolve_revision(repo, head)
    base_sha = resolve_revision(repo, base)

    # Defect 36. Every execution is recorded in order, so the verdict can say
    # how many runs it took and what each one did instead of leaving a reader to
    # infer it from a sentence.
    head_runs: list[Outcome] = []
    base_runs: list[Outcome] = []

    def provenance_failure(exc: RevisionMismatch) -> Verdict:
        return Verdict(
            False,
            f"discarded: revision provenance could not be established ({exc})",
            failure_excerpt=str(exc),
            head_sha=head_sha, base_sha=base_sha,
            disposition=Disposition.PROVENANCE_FAILED,
            head_runs=tuple(head_runs), base_runs=tuple(base_runs),
        )

    try:
        head_dir = head_ctx.__enter__() if head_ctx else Path(head_workdir)  # type: ignore[arg-type]
        try:
            verify_workdir(head_dir, head_sha, "head")
        except RevisionMismatch as exc:
            return provenance_failure(exc)

        # Defect 35. Clean once per candidate, before its first execution on
        # this side. Deliberately NOT before every execution: the reruns below
        # exist to detect non-determinism, and a candidate that is flaky because
        # it accumulates state must stay flaky here or it will be believed.
        reset_workdir(head_dir)
        first = run_test(head_dir, test_code, timeout_s)
        head_runs.append(first.outcome)
        if first.outcome is Outcome.ERROR:
            return Verdict(False, "discarded: test could not be collected on head",
                           failure_excerpt=first.tail, head_outcome=first.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.HEAD_UNCOLLECTABLE,
                           head_runs=tuple(head_runs),
                           failure_kind=first.failure_kind)
        if first.outcome is Outcome.TIMEOUT:
            return Verdict(False, "discarded: timed out on head",
                           failure_excerpt=first.tail, head_outcome=first.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.HEAD_TIMEOUT,
                           head_runs=tuple(head_runs),
                           failure_kind=first.failure_kind)
        if first.outcome is Outcome.NOTRUN:
            return Verdict(False, "discarded: no test actually executed on head "
                                  "(every collected test was skipped, or none "
                                  "was collected)",
                           failure_excerpt=first.tail, head_outcome=first.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.HEAD_NOTRUN,
                           head_runs=tuple(head_runs))
        if first.outcome is Outcome.PASS:
            return Verdict(False, "discarded: passes on head, so it is a hardening "
                                  "test rather than a catching test",
                           head_outcome=first.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.HEAD_PASSED,
                           head_runs=tuple(head_runs))

        # It failed on head. Prove the failure is not luck before we spend a
        # base checkout on it, and long before we spend a reviewer's attention.
        for _ in range(max(0, reruns - 1)):
            again = run_test(head_dir, test_code, timeout_s)
            head_runs.append(again.outcome)
            if again.outcome is not Outcome.FAIL:
                return Verdict(False, "discarded: non-deterministic across reruns "
                                      "on head (flaky)",
                               failure_excerpt=first.tail,
                               head_outcome=first.outcome,
                               head_sha=head_sha, base_sha=base_sha,
                               disposition=Disposition.HEAD_FLAKY,
                               head_runs=tuple(head_runs),
                               failure_kind=first.failure_kind)

        base_dir = base_ctx.__enter__() if base_ctx else Path(base_workdir)  # type: ignore[arg-type]
        try:
            verify_workdir(base_dir, base_sha, "base")
        except RevisionMismatch as exc:
            return provenance_failure(exc)
        # Anything the head executions wrote must not be visible on base.
        reset_workdir(base_dir)
        on_base = run_test(base_dir, test_code, timeout_s)
        base_runs.append(on_base.outcome)

        if on_base.outcome is Outcome.PASS:
            return Verdict(True, "catching: passes on base, fails on head",
                           failure_excerpt=first.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.CATCHING,
                           head_runs=tuple(head_runs), base_runs=tuple(base_runs),
                           failure_kind=first.failure_kind)
        if on_base.outcome is Outcome.FAIL:
            return Verdict(False, "discarded: fails on base too, so the fault is "
                                  "pre-existing rather than caused by this change",
                           latent=True, failure_excerpt=first.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.HEAD_FAILED_BASE_FAILED_LATENT,
                           head_runs=tuple(head_runs), base_runs=tuple(base_runs),
                           failure_kind=first.failure_kind)
        if on_base.outcome is Outcome.NOTRUN:
            # The dangerous one. Previously this returned exit code 0, was read
            # as PASS, and produced "catching: passes on base, fails on head"
            # for a test that never ran on base at all - including when the
            # symbol under test did not yet exist on that revision.
            return Verdict(False, "discarded: no test executed on base, so "
                                  "'passes on base' cannot be established",
                           failure_excerpt=on_base.tail,
                           head_outcome=first.outcome, base_outcome=on_base.outcome,
                           head_sha=head_sha, base_sha=base_sha,
                           disposition=Disposition.BASE_NOTRUN,
                           head_runs=tuple(head_runs), base_runs=tuple(base_runs),
                           failure_kind=first.failure_kind)
        return Verdict(False, "discarded: could not be collected on base, so no "
                              "comparison is possible",
                       failure_excerpt=on_base.tail,
                       head_outcome=first.outcome, base_outcome=on_base.outcome,
                       head_sha=head_sha, base_sha=base_sha,
                       disposition=Disposition.BASE_UNCOLLECTABLE,
                       head_runs=tuple(head_runs), base_runs=tuple(base_runs),
                       failure_kind=first.failure_kind)
    finally:
        if base_ctx:
            base_ctx.__exit__(None, None, None)
        if head_ctx:
            head_ctx.__exit__(None, None, None)
