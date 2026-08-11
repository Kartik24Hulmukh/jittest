"""Tests for jittest verify MVP on synthetic two-commit fixture repository."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from jittest.diff import git_env
from jittest.verify import VerdictClass, verify_test


def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(cwd)] + list(args),
        capture_output=True,
        text=True,
        check=True,
        env=git_env(),
    )
    return res.stdout.strip()


def create_synthetic_repo(tmp_dir: Path) -> tuple[Path, str, str, Path]:
    repo = tmp_dir / "synthetic_repo"
    repo.mkdir()

    # Git init
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    # Base commit: valid function
    src_dir = repo / "src"
    src_dir.mkdir()
    app_py = src_dir / "app.py"
    app_py.write_text("def add(a, b):\n    return a + b\n")

    test_file = repo / "test_app.py"
    test_file.write_text("from src.app import add\ndef test_add():\n    assert add(2, 3) == 5\n")

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Base commit: working add")
    base_sha = _git(repo, "rev-parse", "HEAD")

    # Head commit: bug introduced in add
    app_py.write_text("def add(a, b):\n    return a - b  # BUG introduced\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Head commit: bug in add")
    head_sha = _git(repo, "rev-parse", "HEAD")

    return repo, base_sha, head_sha, test_file


def test_verify_known_bug_produces_proven_catch():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, test_file = create_synthetic_repo(Path(tmp))
        out_artifact = Path(tmp) / "evidence.json"

        evidence, exit_code = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_file,
            output_path=out_artifact,
        )

        assert exit_code == 0
        assert evidence["verdict"] == VerdictClass.PROVEN_CATCH
        assert evidence["proven_catch"] is True
        assert evidence["disposition"] == "catching"
        assert evidence["base_execution"]["outcome"] == "PASS"
        assert evidence["head_execution"]["outcome"] == "FAIL"
        assert evidence["rerun_agreement"] is True

        assert out_artifact.exists()
        artifact_data = json.loads(out_artifact.read_text(encoding="utf-8"))
        assert artifact_data["verdict"] == VerdictClass.PROVEN_CATCH
        assert "provenance" in artifact_data
        assert artifact_data["provenance"]["base_sha"] == base_sha
        assert artifact_data["provenance"]["head_sha"] == head_sha


def test_verify_non_discriminating_test():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, test_file = create_synthetic_repo(Path(tmp))
        out_artifact = Path(tmp) / "evidence_fixed.json"

        # Compare base_sha to base_sha (no bug introduced)
        evidence, exit_code = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=base_sha,
            test_file_path=test_file,
            output_path=out_artifact,
        )

        assert exit_code == 1
        assert evidence["verdict"] == VerdictClass.NON_DISCRIMINATING
        assert evidence["proven_catch"] is False
        assert evidence["disposition"] == "head_passed"
        assert evidence["base_execution"]["outcome"] == "NOTRUN"  # skipped base because head passed
        assert evidence["head_execution"]["outcome"] == "PASS"

        assert out_artifact.exists()
        artifact_data = json.loads(out_artifact.read_text(encoding="utf-8"))
        assert artifact_data["verdict"] == VerdictClass.NON_DISCRIMINATING
