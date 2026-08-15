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

A fourth warning (premortem P3-9). Every git call below passes env=git_env().
git reads GIT_DIR and GIT_WORK_TREE from the environment and they outrank -C,
so without scrubbing them a hostile or merely untidy environment points these
operations at a different repository than the one under test - and because an
unresolvable revision deliberately skips the provenance check rather than
failing it, the result is a confident verdict about nothing identifiable.

A fifth warning (Defect 42, and the isolation work in jittest.sandbox). A
candidate is executed, so the two facts that decide whether that is safe are
what it can reach and what survives it. _env_for answers the first by
allowlist. _run_process answers the second: a timeout that kills only the
direct child leaves grandchildren holding the shared worktree open, which is
Defect 35 arriving through a door the reset does not cover.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .diff import git_env
from .redact import redact
from .sandbox import SandboxPlan
from .sandbox import wrap as sandbox_wrap

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

# Variables a candidate legitimately needs in order to run at all. Everything
# else is withheld - see _env_for. This cannot simply be PATH: Windows needs
# SYSTEMROOT, COMSPEC and PATHEXT before subprocess or sockets work, and a
# candidate that cannot start is a false NOTRUN, not a security win.
_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE",
    "TZ", "TMPDIR", "TMP", "TEMP", "PWD", "PYTHONUTF8", "PYTHONIOENCODING",
    "VIRTUAL_ENV", "CONDA_PREFIX", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR",
    "COMSPEC", "PATHEXT", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "JITTEST_FORCE_MINIRUNNER",
})

# Second layer. If someone widens the allowlist later and the new name looks
# like a credential, it is still withheld: a leak should require deliberately
# defeating two mechanisms, not just editing one set.
_SECRETISH = re.compile(
    r"KEY|TOKEN|SECRET|PASSWD|PASSWORD|CREDENTIAL|PRIVATE|SESSION|COOKIE"
    r"|NVAPI|AUTH", re.I)


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
    HEAD_UNCOLLECTABLE_BASE_PASSED = "head_uncollectable_base_passed"
    HEAD_UNCOLLECTABLE_BASE_BROKEN = "head_uncollectable_base_broken"
    HEAD_TIMEOUT = "head_timeout"
    HEAD_NOTRUN = "head_notrun"
    HEAD_PASSED = "head_passed"
    HEAD_FLAKY = "head_flaky"
    HEAD_FAILED_BASE_FAILED_LATENT = "head_failed_base_failed_latent"
    BASE_NOTRUN = "base_notrun"
    BASE_UNCOLLECTABLE = "base_uncollectable"
    PROVENANCE_FAILED = "provenance_failed"
    CATCHING = "catching"
    ENV_SETUP_FAILED = "env_setup_failed"
    ENV_BUILD_TIMEOUT = "env_build_timeout"


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
        # Defect 65. Redact here, at the single point where captured output
        # becomes a quotable excerpt, rather than at each of the nine call
        # sites that build a Verdict - one of which would eventually be added
        # without it. Truncate first so the mask cannot be cut in half.
        return redact(combined[-TAIL_LIMIT:])


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


def detect_runner(python_exe: str | Path | None = None) -> list[str]:
    """Prefer the project's own pytest. Fall back to the bundled mini-runner."""
    exe = str(python_exe) if python_exe else sys.executable
    if os.getenv("JITTEST_FORCE_MINIRUNNER") == "1":
        return [exe, "-m", "jittest._minirunner"]
    probe = subprocess.run(
        [exe, "-c", "import pytest"], capture_output=True, text=True, errors="replace",
    )
    if probe.returncode == 0:
        return [exe, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    return [exe, "-m", "jittest._minirunner"]


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
        capture_output=True, text=True, errors="replace", env=git_env(),
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
        capture_output=True, text=True, errors="replace", env=git_env(),
    )
    # Never -x: ignored build artefacts and virtualenvs are part of a usable
    # checkout, and removing them would break the runner rather than isolate it.
    subprocess.run(
        ["git", "-C", str(workdir), "clean", "-qfd",
         "-e", ".jittest*", "-e", "*.egg-info"],
        capture_output=True, text=True, errors="replace", env=git_env(),
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
            capture_output=True, text=True, errors="replace", env=git_env(),
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
            capture_output=True, text=True, errors="replace", env=git_env(),
        )
        if cloned.returncode != 0:
            raise RuntimeError(f"cannot materialise {self.rev}: {cloned.stderr.strip()}")
        subprocess.run(
            ["git", "-C", str(self.path), "checkout", "--quiet", "--detach", self.rev],
            capture_output=True, text=True, errors="replace", check=True, env=git_env(),
        )
        verify_workdir(self.path, self.expected_sha, self.rev)
        return self.path

    def __exit__(self, *exc: object) -> None:
        if self._added:
            subprocess.run(
                ["git", "-C", str(self.repo), "worktree", "remove", "--force",
                 str(self.path)],
                capture_output=True, text=True, errors="replace", env=git_env(),
            )
        shutil.rmtree(self.path, ignore_errors=True)


def _env_for(workdir: Path) -> dict:
    """Build the environment a candidate executes in, by allowlist. Defect 62.

    This used to be ``dict(os.environ)``, which handed model-written code every
    variable the runner held - including the LLM API key that generated the
    candidate and, under CI, a write-capable GITHUB_TOKEN. A generated test is
    untrusted input: reading os.environ and putting the value in an assertion
    message is enough to exfiltrate it into a PR comment. Copying by allowlist
    means a credential added to the runner tomorrow is absent by default rather
    than leaked by default.

    This is environment isolation. It is one of two layers and it is the weaker
    one: it decides what a candidate may read, not where a candidate may reach.
    The boundary lives in ``jittest.sandbox``; this function keeps working when
    no backend is available, which is exactly why that fallback is recorded in
    the report rather than passed over in silence.
    """
    env: dict[str, str] = {}
    for name in _ENV_ALLOWLIST:
        value = os.environ.get(name)
        if value is not None and not _SECRETISH.search(name):
            env[name] = value
    # Set, never inherited: the host's PYTHONPATH is deliberately dropped so
    # host packages cannot shadow the repo under test and change a verdict.
    pythonpath_entries = [
        str(workdir),
        str(workdir / "src"),
        str(workdir / "tests"),
        str(workdir / "testing"),
        str(workdir / "test"),
        str(workdir / "lib"),
        _PACKAGE_ROOT,
    ]
    env["PYTHONPATH"] = os.pathsep.join(
        [p for p in pythonpath_entries if p]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"          # kill one source of ordering flakiness
    env["JITTEST_CHILD"] = "1"
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


def _run_process(command: list[str], cwd: str, env: dict, timeout_s: int):
    """Run a candidate and, on timeout, kill the whole process tree.

    Defect 42. ``subprocess.run(timeout=...)`` kills the direct child only.
    A candidate that spawned anything leaves grandchildren running against a
    shared worktree: they hold file handles that break ``git worktree remove``
    and they write files that the next candidate then reads, which is the
    Defect 35 contamination route re-entering through a door the reset does not
    cover. The process is started in its own session so the entire group can be
    signalled at once.
    """
    popen_kwargs: dict = {}
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    proc = subprocess.Popen(
        command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, errors="replace", **popen_kwargs,
    )
    try:
        out, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        # Reap what we just signalled. If it will not die even now, say so by
        # timing out again rather than blocking the run forever.
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.communicate(timeout=10)
        raise
    return proc.returncode, out or "", err or ""


def _kill_tree(proc: subprocess.Popen) -> None:
    """Best effort: signal the group, then the process. Never raise."""
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
    except OSError:
        # Covers ProcessLookupError: the group is already gone, which is the
        # outcome we wanted anyway.
        pass
    with contextlib.suppress(OSError):
        proc.kill()


def run_test(workdir: Path, test_code: str, timeout_s: int = 120,
             sbx: SandboxPlan | None = None,
             python_path: Path | str | None = None,
             rel_test_path: Path | str | None = None) -> RunResult:
    """Write the candidate into the checkout, run it, then remove it.

    ``sbx`` selects the isolation backend. ``None`` means unconfined, which is
    the historical behaviour and remains the default so that every existing
    caller - including the whole test suite - keeps its meaning. The pipeline
    always passes a plan; see ``jittest.sandbox``.
    """
    workdir = Path(workdir)
    token = uuid.uuid4().hex[:8]
    if rel_test_path:
        target_dir = (workdir / rel_test_path).parent
        target_dir.mkdir(parents=True, exist_ok=True)
        candidate = target_dir / f"{CANDIDATE_PREFIX}{token}.py"
    else:
        candidate = workdir / f"{CANDIDATE_PREFIX}{token}.py"
    candidate.write_text(test_code, encoding="utf-8")
    runner = detect_runner(python_path)
    uses_pytest = "pytest" in runner
    report = workdir / f".jittest-junit-{token}.xml"
    command = [*runner, str(candidate)]
    if uses_pytest:
        command.append(f"--junitxml={report}")
    env = _env_for(workdir)

    if sbx is not None and sbx.isolated:
        command, extra = sandbox_wrap(command, workdir, env, sbx)
        env = extra or env
    try:
        code_, out_, err_ = _run_process(command, str(workdir), env, timeout_s)

        class _P:                     # minimal stand-in for CompletedProcess
            returncode = code_
            stdout = out_
            stderr = err_
        proc = _P()
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
    sbx: SandboxPlan | None = None,
) -> Verdict:
    """Run the candidate on head, then base, and decide. No model involved.

    ``sbx`` is applied identically to both sides. That symmetry is not an
    implementation detail: a candidate executed under different confinement on
    head and on base would produce a difference caused by jittest rather than
    by the diff, which is precisely the class of fabricated catch that Defects
    33 to 35 exist to prevent.
    """
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
        first = run_test(head_dir, test_code, timeout_s, sbx=sbx)
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
            again = run_test(head_dir, test_code, timeout_s, sbx=sbx)
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
        on_base = run_test(base_dir, test_code, timeout_s, sbx=sbx)
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
