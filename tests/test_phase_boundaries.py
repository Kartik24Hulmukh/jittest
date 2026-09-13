"""Public-path regression tests: no candidate phase may bypass P0 policy."""
from __future__ import annotations

import os
from unittest import mock

from jittest import verify as V
from jittest.execute import FailureKind, Outcome, RunResult
from tests.test_verify import create_synthetic_repo


def _run(tmp_path, *, violation=None, readiness=None, observe=False, reproduction=False):
    repo, base, head, test = create_synthetic_repo(tmp_path)
    calls = []
    def execute(*args, **kwargs):
        calls.append(str(args[0]))
        outcome = (Outcome.FAIL if reproduction else Outcome.PASS) if len(calls) == 1 else (Outcome.PASS if reproduction else Outcome.FAIL)
        return RunResult(outcome, returncode=int(outcome is Outcome.FAIL),
                         stdout="AssertionError" if outcome is Outcome.FAIL else "ok",
                         failure_kind=FailureKind.ASSERTION if outcome is Outcome.FAIL else FailureKind.NONE)
    def scan(*args, **kwargs):
        from types import SimpleNamespace
        bad = len(calls) == violation
        return SimpleNamespace(ok=not bad, files=1, total_bytes=1,
                               violations=["injected_boundary_violation"] if bad else [])
    def preflight(workdir, env):
        if len(calls) + 1 == readiness:
            raise V.VerifyRefusalError(V.RefusalReason(code="environment_not_ready"))
        return {"evaluated": True, "ok": True, "mode": "required"}
    with mock.patch.dict(os.environ, {"JITTEST_OUTPUT_GUARD": "observe" if observe else "required"}), mock.patch.object(V, "provision_environment", return_value={}), mock.patch.object(V, "run_test", side_effect=execute), mock.patch.object(V, "_readiness_block", side_effect=preflight), mock.patch("jittest.outputguard.scan_output_tree", side_effect=scan):
        return V.verify_test(repo, base, head, test, no_sandbox=True,
                             signing_key_path=tmp_path / "key"), calls


def test_required_base_output_refuses(tmp_path):
    import pytest
    with pytest.raises(V.VerifyRefusalError) as exc:
        _run(tmp_path, violation=1)
    assert exc.value.reason.code == "output_boundary_violation"


def test_required_rerun_output_refuses(tmp_path):
    import pytest
    with pytest.raises(V.VerifyRefusalError) as exc:
        _run(tmp_path, violation=3)
    assert exc.value.reason.code == "output_boundary_violation"


def test_required_head_readiness_refuses(tmp_path):
    import pytest
    with pytest.raises(V.VerifyRefusalError, match="environment_not_ready"):
        _run(tmp_path, readiness=2)


def test_required_rerun_readiness_refuses(tmp_path):
    import pytest
    with pytest.raises(V.VerifyRefusalError, match="environment_not_ready"):
        _run(tmp_path, readiness=3)


def test_observe_records_all_phases(tmp_path):
    (receipt, rc), calls = _run(tmp_path, violation=3, observe=True)
    assert rc == 0
    phases = receipt["verification_phases"]
    assert [p["phase"] for p in phases] == ["base", "head", "head_rerun_2"]
    assert len(phases) == len(calls) == 3
    assert [p["output_guard"]["ok"] for p in phases] == [True, True, False]
    assert all(p["readiness"]["evaluated"] for p in phases)
    assert all(len(p["revision"]) == 40 for p in phases)
    assert all(len(p["stdout_sha256"]) == 64 for p in phases)


def test_required_probe_output_cannot_be_swallowed(tmp_path):
    import pytest
    with pytest.raises(V.VerifyRefusalError) as exc:
        _run(tmp_path, violation=3, reproduction=True)
    assert exc.value.reason.code == "output_boundary_violation"


def test_real_head_only_manifest_refuses_before_head_execution(tmp_path):
    from tests.test_verify import _git

    repo, base, head, test = create_synthetic_repo(tmp_path)
    (repo / "requirements.txt").write_text("missing-jittest-fixture-package==1.0\n")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "Head-only dependency")
    head = _git(repo, "rev-parse", "HEAD")
    import pytest
    with mock.patch.dict(os.environ, {"JITTEST_READINESS": "required"}), mock.patch.object(V, "provision_environment", return_value={"resolved_versions": []}), mock.patch.object(V, "run_test", return_value=RunResult(Outcome.PASS)) as execute, pytest.raises(V.VerifyRefusalError) as exc:
        V.verify_test(repo, base, head, test, no_sandbox=True,
                          signing_key_path=tmp_path / "key")
    assert exc.value.reason.code == "environment_not_ready"
    assert execute.call_count == 1


def test_required_preexisting_test_output_cannot_be_swallowed(tmp_path):
    from tests.test_verify import _git

    repo, base, head, test = create_synthetic_repo(tmp_path)
    # test_app is excluded; this identical test exists at both revisions below.
    (repo / "test_healthy.py").write_text("def test_healthy():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Unchanged health test")
    revision = _git(repo, "rev-parse", "HEAD")
    import pytest
    with mock.patch.dict(os.environ, {"JITTEST_OUTPUT_GUARD": "required"}), mock.patch.object(V, "run_test", return_value=RunResult(Outcome.PASS)), mock.patch.object(V, "_output_guard_block", side_effect=V.VerifyRefusalError(V.RefusalReason(code="output_boundary_violation"))), pytest.raises(V.VerifyRefusalError) as exc:
        V._verify_pass_to_pass(repo, revision, revision, ".", test.name, None, None, None)
    assert exc.value.reason.code == "output_boundary_violation"
