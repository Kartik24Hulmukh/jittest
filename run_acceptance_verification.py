"""Run acceptance verification on synthetic fixture repository and emit both artifacts."""

import json
import subprocess
import tempfile
from pathlib import Path

from jittest.diff import git_env
from jittest.verify import verify_test


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True,
        text=True,
        check=True,
        env=git_env(),
    )
    return res.stdout.strip()


def run():
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        repo = tmp_dir / "synthetic_repo"
        repo.mkdir()

        _git(repo, "init")
        _git(repo, "config", "user.name", "Test User")
        _git(repo, "config", "user.email", "test@example.com")

        # Base commit: valid calculator function
        src_dir = repo / "src"
        src_dir.mkdir()
        app_py = src_dir / "app.py"
        app_py.write_text("def multiply(a, b):\n    return a * b\n")

        test_file = repo / "test_app.py"
        test_file.write_text("from src.app import multiply\ndef test_multiply():\n    assert multiply(3, 4) == 12\n")

        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "Base commit: working multiply")
        base_sha = _git(repo, "rev-parse", "HEAD")

        # Head commit: bug introduced in multiply
        app_py.write_text("def multiply(a, b):\n    return a + b  # BUG introduced\n")
        _git(repo, "add", ".")
        _git(repo, "commit", "-m", "Head commit: bug in multiply")
        head_sha = _git(repo, "rev-parse", "HEAD")

        # Output dir for artifacts
        scratch_dir = Path.cwd() / "scratch"
        scratch_dir.mkdir(exist_ok=True)
        bug_artifact_path = scratch_dir / "bug_evidence.json"
        fixed_artifact_path = scratch_dir / "fixed_evidence.json"

        # 1. Run on known-bug commit vs base commit -> proven_catch
        bug_evidence, bug_exit = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_file,
            output_path=bug_artifact_path,
        )

        # 2. Run on fixed commit (base vs base) -> non_discriminating
        fixed_evidence, fixed_exit = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=base_sha,
            test_file_path=test_file,
            output_path=fixed_artifact_path,
        )

        print(f"Known-Bug Run Exit Code: {bug_exit} (Verdict: {bug_evidence['verdict']})")
        print(f"Fixed Run Exit Code: {fixed_exit} (Verdict: {fixed_evidence['verdict']})")
        print(f"Saved bug artifact to: {bug_artifact_path}")
        print(f"Saved fixed artifact to: {fixed_artifact_path}")


if __name__ == "__main__":
    run()
