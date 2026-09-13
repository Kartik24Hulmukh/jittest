"""BASE-only runtime selection at public verification and Action boundaries.

Planning tests deliberately stop before provisioning: not a Docker E2E proof.
"""
from __future__ import annotations

from unittest import mock

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover
    import unittest
    raise unittest.SkipTest("requires pytest; exercised by the pytest CI matrix") from exc

from jittest import action as A
from jittest import sandbox as S
from jittest import verify as V
from tests.test_verify import _git, create_synthetic_repo

PIN = "ghcr.io/example/runtime@sha256:" + "a" * 64
EVIL = "ghcr.io/attacker/runtime@sha256:" + "b" * 64


class Planned(Exception):
    """Stop before executing any repository code."""


def _config(repo, text):
    (repo / "pyproject.toml").write_text(text, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "runtime config")
    return _git(repo, "rev-parse", "HEAD")


def _image(repo, image):
    return _config(repo, '[tool.jittest.runtime]\nimage = "' + image + '"\n')


@pytest.mark.parametrize("base_image", [PIN, "", None])
def test_public_plan_uses_base_never_head(tmp_path, monkeypatch, base_image):
    monkeypatch.delenv("JITTEST_RUNTIME_IMAGE", raising=False)
    repo, base, head, test = create_synthetic_repo(tmp_path)
    if base_image is not None:
        base = _image(repo, base_image)
    head = _image(repo, EVIL)
    with mock.patch.object(V, "plan_sandbox", side_effect=Planned) as plan, pytest.raises(Planned):
        V.verify_test(repo, base, head, test, sandbox_mode="required")
    assert plan.call_args.kwargs == {
        "mode": "required", "probe": True, "runtime_image": base_image or ""}


@pytest.mark.parametrize("image", ["python:latest", "python@sha256:123", "bad image"])
def test_invalid_base_pin_refuses_before_planning(tmp_path, monkeypatch, image):
    monkeypatch.delenv("JITTEST_RUNTIME_IMAGE", raising=False)
    repo, _, head, test = create_synthetic_repo(tmp_path)
    base = _image(repo, image)
    with mock.patch.object(V, "plan_sandbox") as plan, pytest.raises(V.VerifyRefusalError) as exc:
        V.verify_test(repo, base, head, test, sandbox_mode="required")
    assert exc.value.reason.code == "image_digest_required"
    assert exc.value.reason.phase == "plan"
    plan.assert_not_called()


def test_missing_base_file_does_not_trust_head(tmp_path, monkeypatch):
    monkeypatch.delenv("JITTEST_RUNTIME_IMAGE", raising=False)
    repo, base, _, _ = create_synthetic_repo(tmp_path)
    _image(repo, EVIL)
    assert S.load_runtime_image(repo, base)[0] == ""
    assert S.load_runtime_image(repo, "not-a-revision")[0] == ""
    assert S.load_runtime_image(repo, None)[0] == EVIL


def test_trusted_operator_env_remains_fallback(tmp_path, monkeypatch):
    repo, base, _, _ = create_synthetic_repo(tmp_path)
    _image(repo, EVIL)
    monkeypatch.setenv("JITTEST_RUNTIME_IMAGE", PIN)
    assert S.load_runtime_image(repo, base)[0] == PIN


@pytest.mark.parametrize("text", ['tool = "bad"', '[tool]\njittest = []', '[tool.jittest]\nruntime = 1'])
def test_non_table_config_is_not_an_image(tmp_path, monkeypatch, text):
    monkeypatch.delenv("JITTEST_RUNTIME_IMAGE", raising=False)
    repo, _, _, _ = create_synthetic_repo(tmp_path)
    base = _config(repo, text)
    _image(repo, EVIL)
    assert S.load_runtime_image(repo, base)[0] == ""


def test_action_preplan_uses_base_pin(tmp_path, monkeypatch):
    repo, _, _, _ = create_synthetic_repo(tmp_path)
    base = _image(repo, PIN)
    head = _image(repo, EVIL)
    (repo / "test_app.py").write_text("def test_changed():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "changed test")
    head = _git(repo, "rev-parse", "HEAD")
    monkeypatch.setenv("JITTEST_BASE", base)
    monkeypatch.setenv("JITTEST_HEAD", head)
    monkeypatch.delenv("JITTEST_RUNTIME_IMAGE", raising=False)
    with mock.patch.object(A, "get_trust_context", return_value="internal"), mock.patch.object(A, "plan_sandbox", side_effect=Planned) as plan, pytest.raises(Planned):
        A.run_action(repo, pr_number=1, output_dir=tmp_path / "artifacts")
    assert plan.call_args.kwargs["runtime_image"] == PIN
