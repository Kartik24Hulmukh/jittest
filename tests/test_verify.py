"""Tests for jittest verify MVP on synthetic two-commit fixture repository."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jittest.diff import git_env
from jittest.execute import FailureKind, Outcome
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


def _run_verify_cli(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(root / "src"), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return subprocess.run(
        [sys.executable, "-m", "jittest.cli", "verify", "--repo", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
        cwd=str(cwd) if cwd else None,
        env=env,
        timeout=300,
    )


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
        assert evidence["base_execution"]["outcome"] == "PASS"  # base executed before head
        assert evidence["head_execution"]["outcome"] == "PASS"

        assert out_artifact.exists()
        artifact_data = json.loads(out_artifact.read_text(encoding="utf-8"))
        assert artifact_data["verdict"] == VerdictClass.NON_DISCRIMINATING


def test_verify_signed_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, test_file = create_synthetic_repo(Path(tmp))
        out_artifact = Path(tmp) / "signed_evidence.json"

        evidence, exit_code = verify_test(
            repo_path=repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=test_file,
            output_path=out_artifact,
            no_sandbox=True,
        )

        assert "signature" in evidence
        assert evidence["signature"]["algorithm"] in ("Ed25519", "HMAC-SHA256")

        from jittest.receipt import verify_receipt
        ok, msg = verify_receipt(out_artifact)
        assert ok is True
        assert "SIGNER_UNVERIFIED" in msg

        pub_key = evidence["signature"]["verifying_key"]
        ok, msg = verify_receipt(out_artifact, expected_signer=pub_key)
        assert ok is True
        assert "SIGNER_TRUSTED" in msg


def test_verify_cli_resolves_relative_test_to_repo_from_other_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, _ = create_synthetic_repo(Path(tmp))
        out_artifact = Path(tmp) / "evidence-from-cli.json"
        other_cwd = Path(tmp) / "elsewhere"
        other_cwd.mkdir()
        proc = _run_verify_cli(
            repo,
            "--base",
            base_sha,
            "--head",
            head_sha,
            "--test",
            "test_app.py",
            "--output",
            str(out_artifact),
            "--json",
            cwd=other_cwd,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == VerdictClass.PROVEN_CATCH
        assert out_artifact.exists()


def test_verify_test_preserves_full_pytest_node_id():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo-node-id"
        repo.mkdir()
        test_file = repo / "tests" / "test_app.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("def test_regression_target():\n    assert True\n", encoding="utf-8")

        class _Plan:
            isolated = False
            backend = "none"
            notes: list[str] = []

            def as_dict(self):
                return {"isolated": False, "backend": "none", "notes": []}

        class _Worktree:
            def __init__(self, *_args, **_kwargs):
                self.path = repo

            def __enter__(self):
                return self.path

            def __exit__(self, *_exc):
                return None

        outcomes = iter([Outcome.PASS, Outcome.FAIL, Outcome.FAIL])
        seen_node_ids: list[str | None] = []

        def _fake_run_test(*_args, **kwargs):
            seen_node_ids.append(kwargs.get("node_id"))
            outcome = next(outcomes)
            return SimpleNamespace(
                outcome=outcome,
                returncode=1 if outcome is Outcome.FAIL else 0,
                stdout="",
                stderr="",
                failure_kind=FailureKind.ASSERTION,
            )

        with mock.patch("jittest.verify.resolve_revision", side_effect=["a" * 40, "b" * 40]), \
             mock.patch("jittest.verify.plan_sandbox", return_value=_Plan()), \
             mock.patch("jittest.verify.Worktree", _Worktree), \
             mock.patch("jittest.verify.provision_environment", return_value={"python_path": None}), \
             mock.patch("jittest.verify.run_test", side_effect=_fake_run_test), \
             mock.patch("jittest.verify.sign_evidence", side_effect=lambda evidence, key_path=None: evidence), \
             mock.patch("jittest.verify._get_git_sha", return_value=""), \
             mock.patch("jittest.verify._get_git_branch", return_value=""), \
             mock.patch("jittest.verify._get_git_dirty", return_value=False):
            evidence, exit_code = verify_test(
                repo_path=repo,
                base_ref="base",
                head_ref="head",
                test_file_path="tests/test_app.py::Suite::test_regression_target",
            )

        assert exit_code == 0
        assert evidence["verdict"] == VerdictClass.PROVEN_CATCH
        assert seen_node_ids and all(n == "Suite::test_regression_target" for n in seen_node_ids)


def test_verify_cli_refuses_missing_or_empty_tests_without_traceback():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, _ = create_synthetic_repo(Path(tmp))

        missing = _run_verify_cli(repo, "--base", base_sha, "--head", head_sha, "--test", "missing_test.py")
        assert missing.returncode == 2
        assert "test file not found" in missing.stderr
        assert "Traceback (most recent call last)" not in missing.stderr

        empty_file = repo / "empty_test.py"
        empty_file.write_text("", encoding="utf-8")
        empty = _run_verify_cli(repo, "--base", base_sha, "--head", head_sha, "--test", "empty_test.py")
        assert empty.returncode == 2
        assert "test file is empty" in empty.stderr
        assert "Traceback (most recent call last)" not in empty.stderr


def test_verify_cli_refuses_nonexistent_base_and_head_revisions_cleanly():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, _ = create_synthetic_repo(Path(tmp))

        bad_base = _run_verify_cli(repo, "--base", "no-such-base-ref", "--head", head_sha, "--test", "test_app.py")
        assert bad_base.returncode == 2
        assert "base revision not found: no-such-base-ref" in bad_base.stderr
        assert "Traceback (most recent call last)" not in bad_base.stderr

        bad_head = _run_verify_cli(repo, "--base", base_sha, "--head", "no-such-head-ref", "--test", "test_app.py")
        assert bad_head.returncode == 2
        assert "head revision not found: no-such-head-ref" in bad_head.stderr
        assert "Traceback (most recent call last)" not in bad_head.stderr


def test_verify_cli_json_output_is_parseable_complete_receipt():
    with tempfile.TemporaryDirectory() as tmp:
        repo, base_sha, head_sha, _ = create_synthetic_repo(Path(tmp))
        out_artifact = Path(tmp) / "cli-receipt.json"
        proc = _run_verify_cli(
            repo,
            "--base",
            base_sha,
            "--head",
            head_sha,
            "--test",
            "test_app.py",
            "--output",
            str(out_artifact),
            "--json",
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        for key in ("schema_version", "verdict", "verdict_text", "signature", "base_execution", "head_execution", "provenance"):
            assert key in payload
        file_payload = json.loads(out_artifact.read_text(encoding="utf-8"))
        assert file_payload["signature"]["algorithm"] == "Ed25519"
