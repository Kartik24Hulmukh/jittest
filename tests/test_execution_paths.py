"""Preparation must not write outside the selected checkout, even before sandboxing."""
from pathlib import Path
from unittest import mock

try:
    import pytest
except ModuleNotFoundError as exc:  # dependency-free unittest discovery
    import unittest

    raise unittest.SkipTest("requires pytest; exercised in the pytest CI leg") from exc

from jittest import execute, verify
from tests.test_verify import create_synthetic_repo


@pytest.mark.parametrize("relative", ["../outside/test.py", "/tmp/jittest-escape/test.py", r"C:\outside\test.py", r"..\outside\test.py"])
def test_candidate_rejects_unsafe_path_before_writing(tmp_path, relative):
    work = tmp_path / "work"
    work.mkdir()
    with mock.patch.object(Path, "write_text") as write, mock.patch.object(execute, "_run_process") as run, pytest.raises(verify.VerifyRefusalError) as exc:
        execute.run_test(work, "assert True", rel_test_path=relative)
    assert exc.value.reason.code == "unsafe_execution_path"
    write.assert_not_called()
    run.assert_not_called()


def test_candidate_rejects_symlink_parent_before_writing(tmp_path):
    work = tmp_path / "work"
    outside = tmp_path / "outside"
    work.mkdir()
    outside.mkdir()
    try:
        (work / "tests").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with mock.patch.object(execute, "_run_process") as run, pytest.raises(verify.VerifyRefusalError):
        execute.run_test(work, "assert True", rel_test_path="tests/test_app.py")
    assert list(outside.iterdir()) == []
    run.assert_not_called()


@pytest.mark.parametrize("relative", ["../outside", "/tmp", r"C:\outside", r"..\outside"])
def test_verify_rejects_unsafe_root_before_provision(tmp_path, relative):
    repo, base, head, test = create_synthetic_repo(tmp_path)
    with mock.patch.object(verify, "provision_environment") as provision, pytest.raises(verify.VerifyRefusalError) as exc:
        verify.verify_test(repo, base, head, test, rel_path=relative, no_sandbox=True)
    assert exc.value.reason.code == "unsafe_execution_path"
    provision.assert_not_called()


def test_verify_subproject_places_candidate_relative_to_selected_root(tmp_path):
    repo, base, head, test = create_synthetic_repo(tmp_path)
    nested = repo / "src" / "test_nested.py"
    nested.write_text("def test_ok():\n    assert True\n")
    with mock.patch.object(verify, "provision_environment", return_value={}), mock.patch.object(verify, "run_test", return_value=execute.RunResult(execute.Outcome.PASS)) as run:
        verify.verify_test(repo, base, head, nested, rel_path="src", no_sandbox=True, signing_key_path=tmp_path / "key")
    assert run.call_count == 2
    assert all(call.kwargs["rel_test_path"] == Path("test_nested.py") for call in run.call_args_list)


def test_verify_rejects_candidate_outside_selected_subproject(tmp_path):
    repo, base, head, test = create_synthetic_repo(tmp_path)
    with mock.patch.object(verify, "provision_environment") as provision, pytest.raises(verify.VerifyRefusalError):
        verify.verify_test(repo, base, head, test, rel_path="src", no_sandbox=True)
    provision.assert_not_called()


@pytest.mark.parametrize("phase", ["base", "head"])
def test_selected_root_symlink_refused_in_each_checkout(tmp_path, phase):
    from tests.test_verify import _git

    repo, base, head, test = create_synthetic_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (repo / "subproject").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    _git(repo, "add", "subproject")
    _git(repo, "commit", "-m", "symlink fixture")
    bad = _git(repo, "rev-parse", "HEAD")
    (repo / "subproject").unlink()
    (repo / "subproject").mkdir()
    nested = repo / "subproject" / "test_app.py"
    nested.write_text("def test_ok():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "regular subproject")
    good = _git(repo, "rev-parse", "HEAD")
    with mock.patch.object(verify, "provision_environment", return_value={}) as provision, mock.patch.object(verify, "run_test", return_value=execute.RunResult(execute.Outcome.PASS)), pytest.raises(verify.VerifyRefusalError) as exc:
        verify.verify_test(repo, bad if phase == "base" else good, good if phase == "base" else bad, nested, rel_path="subproject", no_sandbox=True)
    assert exc.value.reason.code == "unsafe_execution_path"
    assert provision.call_count == (0 if phase == "base" else 1)
    assert list(outside.iterdir()) == []


def test_real_subproject_proven_catch(tmp_path):
    from jittest import _ed25519
    from jittest.receipt import get_or_create_signing_key, verify_receipt
    from tests.test_verify import _git

    repo, base, head, _ = create_synthetic_repo(tmp_path)
    test = repo / "src" / "test_nested.py"
    test.write_text("from app import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    key = tmp_path / "key"
    signer = _ed25519.secret_to_public(get_or_create_signing_key(key)).hex()
    receipt, rc = verify.verify_test(repo, base, head, test, rel_path="src", no_sandbox=True, signing_key_path=key)
    assert rc == 0 and receipt["verdict"] == "proven_catch"
    assert [p["phase"] for p in receipt["verification_phases"]] == ["base", "head", "head_rerun_2"]
    assert verify_receipt(receipt, expected_signer=signer, strict_signer=True, expected_base=base, expected_head=head).valid
    assert _git(repo, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert not list(repo.rglob("test_jittest_candidate_*"))


def test_subproject_health_tests_use_root_relative_paths(tmp_path):
    from tests.test_verify import _git

    repo, base, head, test = create_synthetic_repo(tmp_path)
    (repo / "src" / "test_health.py").write_text("def test_ok():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "health test")
    rev = _git(repo, "rev-parse", "HEAD")
    with mock.patch.object(verify, "run_test", return_value=execute.RunResult(execute.Outcome.PASS)) as run:
        assert verify._verify_pass_to_pass(repo, rev, rev, "src", test.name, None, None, None)
    assert run.call_count == 2
    assert all(c.kwargs["rel_test_path"] == Path("test_health.py") for c in run.call_args_list)
