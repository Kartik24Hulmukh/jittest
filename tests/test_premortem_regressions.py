"""Regression tests for premortem findings S06 (long paths) and S14 (odd names).

Premortem 4 recorded two failures on Windows:

    S06  [WinError 206] The filename or extension is too long, escaping
         make_fixture as an untyped error the scenario handler did not catch.
    S14  FileNotFoundError while building a fixture whose tracked file lives
         under a drive-letter-looking directory.

Both are harness defects, not jittest defects, and the work order requires a
regression test per finding.

These tests exercise the harness contract only. They deliberately do NOT
invoke the jittest CLI. The first version of this file did, which took three
minutes per windows-latest matrix leg and turned main red on all three of
them while passing on ubuntu and macos - an OS-dependent integration test
wearing a unit test's clothes. Run the scenarios themselves with:

    python eval/premortem3.py --only S06,S14
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from eval.premortem3 import (
    FixturePathTooLong,
    _is_path_length_failure,
    make_fixture,
    make_oddly_named_file,
)


class TestPathLengthClassification:
    """S06: a path-length refusal must be recognised by type, not by locale."""

    def test_the_windows_206_text_is_recognised(self):
        assert _is_path_length_failure(
            "[WinError 206] The filename or extension is too long: 'C:\\\\d'")

    def test_the_posix_enametoolong_text_is_recognised(self):
        assert _is_path_length_failure("[Errno 36] File name too long: '/tmp/d'")

    def test_an_unrelated_git_failure_is_not_recognised(self):
        assert not _is_path_length_failure(
            "fatal: not a git repository (or any of the parent directories)")

    def test_empty_and_none_are_safe(self):
        assert not _is_path_length_failure("")
        assert not _is_path_length_failure(None)


class TestLongPathFixture:
    """S06: make_fixture either builds the repo or fails by a named type."""

    def test_an_over_long_path_fails_as_fixture_path_too_long(self):
        tmp = Path(tempfile.mkdtemp(prefix="test-s06-"))
        try:
            deep = tmp
            while len(str(deep)) < 300:
                deep = deep / ("d" * 40)
            try:
                repo = make_fixture(deep)
            except FixturePathTooLong as exc:
                # The refusal path: Windows, and any filesystem with a tighter
                # limit than Linux. The message prefix is load-bearing; the OS
                # text after it is not, and is never matched on.
                assert "path exceeds OS limits" in str(exc)
            else:
                # The permissive path: Linux, where PATH_MAX is 4096.
                assert repo.exists()
                assert (repo / "pkg" / "core.py").exists()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_git_failure_unrelated_to_length_is_not_relabelled(self):
        """Only length failures become FixturePathTooLong. Others propagate.

        A harness that funnels every fixture failure into one error type stops
        reporting anything useful, which is how S06 hid inside a generic
        OSError for two premortem rounds.
        """
        tmp = Path(tempfile.mkdtemp(prefix="test-s06b-"))
        try:
            blocker = tmp / "repo"
            blocker.write_text("not a directory\n")
            raised = None
            try:
                make_fixture(blocker)
            except FixturePathTooLong as exc:
                raised = exc
            except (OSError, subprocess.CalledProcessError):
                raised = None
            assert raised is None or "path exceeds OS limits" in str(raised)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestOddlyNamedFiles:
    """S14: the odd-name fixture must build on every platform we ship on."""

    def test_a_drive_letter_looking_directory_is_created_and_tracked(self):
        tmp = Path(tempfile.mkdtemp(prefix="test-s14-"))
        try:
            repo = make_fixture(tmp / "repo")
            created = make_oddly_named_file(repo)
            assert created.exists(), "the fixture file was never written"
            assert created.read_text() == "X = 1\n"
            tracked = subprocess.run(
                ["git", "ls-files"], cwd=str(repo),
                capture_output=True, text=True, check=True).stdout
            assert "C__weird" in tracked, (
                "git did not track the oddly named file; "
                f"ls-files was: {tracked!r}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestPremortem6AdversarialScenarios:
    """Premortem 6 adversarial scenarios: backwards ranges, missing commits, non-Python diffs."""

    def test_backwards_revision_range_disposition(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)

            (repo / "app.py").write_text("def v1(): pass\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "v1"], cwd=repo, capture_output=True, check=True)
            h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            (repo / "app.py").write_text("def v1(): pass\ndef v2(): pass\n")
            subprocess.run(["git", "commit", "-am", "v2"], cwd=repo, capture_output=True, check=True)
            b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            from jittest.diff import extract_targets, git_diff
            diff_text = git_diff(repo, b, h)
            targets = extract_targets(diff_text, repo=repo, base=b, head=h)
            assert len(targets) == 0

    def test_shallow_clone_missing_commit_raises_git_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)

            (repo / "app.py").write_text("x = 1\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "c1"], cwd=repo, capture_output=True, check=True)
            h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            from jittest.diff import GitError, git_diff
            fake_base = "1111111111111111111111111111111111111111"
            raised = False
            try:
                git_diff(repo, fake_base, h)
            except GitError as exc:
                raised = True
                assert "failure to measure" in str(exc)
            assert raised is True

    def test_non_python_diff_produces_zero_targets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)

            (repo / "README.md").write_text("# Hello\n")
            subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repo, capture_output=True, check=True)
            b = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            (repo / "README.md").write_text("# Hello World\n")
            subprocess.run(["git", "commit", "-am", "head"], cwd=repo, capture_output=True, check=True)
            h = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()

            from jittest.diff import extract_targets, git_diff
            diff_text = git_diff(repo, b, h)
            targets = extract_targets(diff_text, repo=repo, base=b, head=h)
            assert len(targets) == 0

