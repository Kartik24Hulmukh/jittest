"""A hostile git environment must not redirect jittest at another repository.

Premortem P3 scenario 9. git reads GIT_DIR, GIT_WORK_TREE and friends from the
environment, and they take precedence over the working directory. `git -C <repo>`
does NOT override them: -C changes the directory git starts from, while GIT_DIR
names the object store outright. So a CI job, a git hook, a `git rebase --exec`,
or a developer with these exported in their shell made every git subprocess
jittest launches read a different repository than the one passed to --repo.

The observed behaviour before this fix, from a real end-to-end run of the CLI:
with GIT_DIR pointing at an unrelated repo, `jittest run --repo target` reported
diff_status="git_failed" and exited 0. That is the Defect 22 shape again - a
failure to measure wearing the costume of "nothing to do". The worse shape is
reachable too: if the decoy repository happens to contain the requested
revisions, the diff, the targets and the verdicts are all about code the user
never asked about, and the run looks completely healthy.

The fix scrubs the repo-pointing variables from the environment of every git
subprocess. jittest is always explicit about which repository it means, so there
is no case in which inheriting these helps.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest.diff import (
    _REPO_POINTING_GIT_VARS,
    GitError,
    extract_targets,
    git_diff,
    git_env,
    git_show,
)

BASE = """\
def discount(price, pct):
    if pct < 0 or pct > 100:
        raise ValueError("pct out of range")
    return price - (price * pct / 100.0)
"""

HEAD = BASE.replace("/ 100.0", "/ 10.0")

DECOY = "def unrelated_thing(x):\n    return x * 2\n"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    env = git_env()
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    return subprocess.run(
        ["git", *args], cwd=str(cwd), env=env,
        capture_output=True, text=True, errors="replace",
    )


def _repo(root: Path, filename: str, base: str, head: str) -> tuple[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    (root / filename).write_text(base)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    base_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / filename).write_text(head)
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "head")
    head_sha = _git(root, "rev-parse", "HEAD").stdout.strip()
    return base_sha, head_sha


class _HostileEnv:
    """Export GIT_DIR/GIT_WORK_TREE at the decoy for the duration of a block."""

    def __init__(self, decoy: Path) -> None:
        self.decoy = decoy
        self.saved: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for name, value in (
            ("GIT_DIR", str(self.decoy / ".git")),
            ("GIT_WORK_TREE", str(self.decoy)),
        ):
            self.saved[name] = os.environ.get(name)
            os.environ[name] = value

    def __exit__(self, *exc: object) -> None:
        for name, old in self.saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


class GitEnvScrubbing(unittest.TestCase):
    def test_repo_pointing_vars_are_removed(self) -> None:
        for name in _REPO_POINTING_GIT_VARS:
            with self.subTest(name=name):
                saved = os.environ.get(name)
                os.environ[name] = "/nonexistent/decoy"
                try:
                    self.assertNotIn(name, git_env())
                finally:
                    if saved is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = saved

    def test_ordinary_variables_survive(self) -> None:
        """Scrubbing must not turn into an allowlist: git needs PATH to run."""
        env = git_env()
        for name in ("PATH",):
            if name in os.environ:
                self.assertEqual(env.get(name), os.environ[name])

    def test_accepts_an_explicit_base_mapping(self) -> None:
        env = git_env({"PATH": "/usr/bin", "GIT_DIR": "/decoy/.git"})
        self.assertEqual(env, {"PATH": "/usr/bin"})

    def test_scrubbing_is_idempotent(self) -> None:
        self.assertEqual(git_env(git_env()), git_env())


class HostileGitDirEndToEnd(unittest.TestCase):
    """The regression itself, through the real functions, with real repositories."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="jittest-hostile-"))
        self.target = self.tmp / "target"
        self.decoy = self.tmp / "decoy"
        self.base, self.head = _repo(self.target, "pricing.py", BASE, HEAD)
        _repo(self.decoy, "unrelated.py", DECOY, DECOY.replace("* 2", "* 3"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_git_diff_reads_the_named_repo_not_git_dir(self) -> None:
        with _HostileEnv(self.decoy):
            text = git_diff(self.target, self.base, self.head)
        self.assertIn("pricing.py", text)
        self.assertNotIn("unrelated.py", text)
        self.assertNotIn("unrelated_thing", text)

    def test_targets_come_from_the_named_repo(self) -> None:
        with _HostileEnv(self.decoy):
            text = git_diff(self.target, self.base, self.head)
            targets = extract_targets(text, self.target, self.base, self.head)
        names = {t.symbol for t in targets}
        self.assertIn("discount", names)
        self.assertNotIn("unrelated_thing", names)

    def test_git_show_reads_the_named_repo(self) -> None:
        with _HostileEnv(self.decoy):
            source = git_show(self.target, self.base, "pricing.py")
        self.assertIn("def discount", source)

    def test_no_git_error_under_a_hostile_environment(self) -> None:
        """The pre-fix symptom was a GitError, reported as diff_status git_failed."""
        with _HostileEnv(self.decoy):
            try:
                git_diff(self.target, self.base, self.head)
            except GitError as exc:  # pragma: no cover - this is the regression
                self.fail(f"hostile GIT_DIR still breaks git_diff: {exc}")

    def test_a_genuinely_bad_revision_still_raises(self) -> None:
        """Scrubbing must not paper over real git failures."""
        with self.assertRaises(GitError):
            git_diff(self.target, "nosuchrev", "alsonope")


if __name__ == "__main__":
    unittest.main()
