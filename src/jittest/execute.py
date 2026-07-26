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
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = [
    "Outcome", "RunResult", "Verdict", "Worktree", "run_test",
    "differential_check", "detect_runner", "CANDIDATE_PREFIX",
]

CANDIDATE_PREFIX = "test_jittest_candidate_"
_PACKAGE_ROOT = str(Path(__file__).resolve().parent.parent)


class Outcome(Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"       # could not be collected or imported
    TIMEOUT = "timeout"


@dataclass
class RunResult:
    outcome: Outcome
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def tail(self, limit: int = 2500) -> str:
        combined = (self.stdout + "\n" + self.stderr).strip()
        return combined[-limit:]


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
        [sys.executable, "-c", "import pytest"], capture_output=True, text=True,
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
            capture_output=True, text=True,
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
            capture_output=True, text=True,
        )
        if cloned.returncode != 0:
            raise RuntimeError(f"cannot materialise {self.rev}: {cloned.stderr.strip()}")
        subprocess.run(
            ["git", "-C", str(self.path), "checkout", "--quiet", "--detach", self.rev],
            capture_output=True, text=True, check=True,
        )
        return self.path

    def __exit__(self, *exc: object) -> None:
        if self._added:
            subprocess.run(
                ["git", "-C", str(self.repo), "worktree", "remove", "--force",
                 str(self.path)],
                capture_output=True, text=True,
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


def run_test(workdir: Path, test_code: str, timeout_s: int = 120) -> RunResult:
    """Write the candidate into the checkout, run it, then remove it."""
    workdir = Path(workdir)
    candidate = workdir / f"{CANDIDATE_PREFIX}{uuid.uuid4().hex[:8]}.py"
    candidate.write_text(test_code, encoding="utf-8")
    runner = detect_runner()
    try:
        proc = subprocess.run(
            [*runner, str(candidate)],
            cwd=str(workdir), env=_env_for(workdir),
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return RunResult(Outcome.TIMEOUT, -1, "", f"timed out after {timeout_s}s")
    finally:
        candidate.unlink(missing_ok=True)

    code = proc.returncode
    if code == 0:
        outcome = Outcome.PASS
    elif code == 1:
        outcome = Outcome.FAIL
    else:
        # pytest: 2 usage/collection, 3 internal, 4 usage, 5 no tests collected.
        outcome = Outcome.ERROR
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
        return Verdict(False, "discarded: could not be collected on base, so no "
                              "comparison is possible",
                       failure_excerpt=on_base.tail,
                       head_outcome=first.outcome, base_outcome=on_base.outcome)
    finally:
        if base_ctx:
            base_ctx.__exit__(None, None, None)
        if head_ctx:
            head_ctx.__exit__(None, None, None)
