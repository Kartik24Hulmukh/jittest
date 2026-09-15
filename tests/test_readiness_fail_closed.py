"""Public readiness must never silently discard compatibility constraints."""

import unittest

try:
    import pytest
except ImportError:
    raise unittest.SkipTest("requires pytest; zero-dependency discovery supported") from None

from jittest.verify import VerifyRefusalError, _readiness_block, _run_guarded_phase


@pytest.mark.parametrize("inventory", [{"Flask": "2.0.0"}, ["Flask==2.0.0"]])
def test_public_version_conflict(tmp_path, monkeypatch, inventory):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text("Flask>=3.0.0", encoding="utf-8")
    with pytest.raises(VerifyRefusalError, match="cannot satisfy"):
        _readiness_block(tmp_path, {"resolved_versions": inventory})


@pytest.mark.parametrize("requirement", [
    "-r other.txt", "-c constraints.txt", "-e .", "not a requirement!",
    "flask[async]==3.0.0", 'flask; python_version < "3.0"',
    "flask @ https://example.invalid/pkg.whl", "flask==3.0rc1",
    "flask!=3.*", "flask~=3.0", "flask===3.0", "flask>=banana",
    "flask " + chr(92),
])
def test_unsupported_input_refuses_without_echoing_content(tmp_path, monkeypatch, requirement):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text(requirement, encoding="utf-8")
    with pytest.raises(VerifyRefusalError) as exc:
        _readiness_block(tmp_path, {"resolved_versions": ["flask==3.0.0"]})
    assert exc.value.reason.code == "environment_not_ready"
    assert exc.value.reason.message == "readiness_error:ValueError"


@pytest.mark.parametrize("inventory", [
    ["flask"], ["flask==3.0rc1"], ["flask==3", "Flask==2"],
    {"flask": True}, {"flask": ""}, False,
    ["-e https://example.invalid/secret"], ["garbage !"],
])
def test_untrusted_or_ambiguous_inventory_refuses(tmp_path, monkeypatch, inventory):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text("flask>=3", encoding="utf-8")
    with pytest.raises(VerifyRefusalError):
        _readiness_block(tmp_path, {"resolved_versions": inventory})


@pytest.mark.parametrize("inventory", [["Flask_Foo==3.1.0"], {"Flask.Foo": "3.1.0"}])
def test_supported_version_range_passes(tmp_path, monkeypatch, inventory):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text("flask-foo>=3,<4,!=3.2 # comment", encoding="utf-8")
    assert _readiness_block(tmp_path, {"resolved_versions": inventory})["ok"]


def test_unsupported_lock_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text("flask", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("-r secret.txt", encoding="utf-8")
    with pytest.raises(VerifyRefusalError):
        _readiness_block(tmp_path, {"resolved_versions": ["flask==3"]})


def test_observe_does_not_claim_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("JITTEST_READINESS", "observe")
    (tmp_path / "requirements.txt").write_text("flask[async]", encoding="utf-8")
    block = _readiness_block(tmp_path, {"resolved_versions": ["flask==3"]})
    assert block["evaluated"] is False
    assert "ok" not in block


def test_required_refusal_prevents_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("JITTEST_READINESS", "required")
    (tmp_path / "requirements.txt").write_text("flask>=3", encoding="utf-8")
    def forbidden(*args, **kwargs):
        pytest.fail("candidate executed after incompatible readiness")
    monkeypatch.setattr("jittest.verify.run_test", forbidden)
    records = []
    with pytest.raises(VerifyRefusalError) as exc:
        _run_guarded_phase(tmp_path, "def test_x(): pass", phase="base", revision="a" * 40,
                           env_info={"resolved_versions": ["flask==2"]}, records=records)
    assert len(exc.value.verification_phases) == 1
    assert records[0]["refusal"]["code"] == "environment_not_ready"


def test_cli_real_version_conflict_emits_signed_refusal(tmp_path, monkeypatch, capsys):
    import json

    from jittest.cli import main
    from jittest.execute import Outcome, RunResult
    from jittest.receipt import verify_receipt
    from tests.test_verify import _git, create_synthetic_repo

    repo, base, head, test = create_synthetic_repo(tmp_path)
    (repo / "requirements.txt").write_text("flask>=3", encoding="utf-8")
    _git(repo, "add", "requirements.txt")
    _git(repo, "commit", "-m", "HEAD requires a newer dependency")
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("JITTEST_READINESS", "required")
    monkeypatch.setattr("jittest.verify.provision_environment",
                        lambda *a, **kw: {"resolved_versions": ["Flask==2.0"]})
    calls = []
    def execute(*args, **kwargs):
        calls.append(True)
        return RunResult(Outcome.PASS, returncode=0, stdout="PRIVATE_OUTPUT")
    monkeypatch.setattr("jittest.verify.run_test", execute)
    artifact = tmp_path / "refusal.json"
    rc = main(["verify", "--repo", str(repo), "--base", base, "--head", head,
               "--test", str(test), "--no-sandbox", "--output", str(artifact),
               "--signing-key", str(tmp_path / "test-only-key"), "--json"])
    assert rc == 2
    assert len(calls) == 1  # BASE ran; incompatible HEAD never executed.
    receipt = json.loads(artifact.read_text())
    assert receipt == json.loads(capsys.readouterr().out)
    assert receipt["verification_phases"][0]["outcome"] == "PASS"
    assert receipt["verification_phases"][1]["refused"] is True
    assert receipt["proven_catch"] is False
    assert "PRIVATE_OUTPUT" not in artifact.read_text()
    assert verify_receipt(receipt).signature_valid is True
