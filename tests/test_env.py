import contextlib
import tempfile
from pathlib import Path

import pytest

from jittest.env import _compute_lockfile_hash, get_venv_python


def test_lockfile_hash_includes_test_requirements():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
        (root / "requirements-dev.txt").write_text("pytest\n", encoding="utf-8")

        h1 = _compute_lockfile_hash(root)
        assert len(h1) == 64

        (root / "requirements-dev.txt").write_text("pytest>=8.0\n", encoding="utf-8")
        h2 = _compute_lockfile_hash(root)
        assert h1 != h2


def test_get_venv_python_path():
    venv = Path("/tmp/fake_venv")
    py = get_venv_python(venv)
    assert "python" in py.name


def test_dependency_bearing_refuses_before_installer():
    import subprocess
    from unittest import mock

    from jittest.env import provision_environment
    from jittest.sandbox import SandboxPlan
    from jittest.verify import VerifyRefusalError

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        (root / "pyproject.toml").write_text(
            """
[project]
name = "dep_test"
version = "0.1.0"
dependencies = ["requests>=2.0"]
""",
            encoding="utf-8",
        )
        sbx = SandboxPlan(backend="docker", image="python:3.13-slim")
        sbx.mode = "required"

        installer_calls = []

        def spy_run(cmd, *args, **kwargs):
            cmd_list = list(cmd) if isinstance(cmd, (list, tuple)) else [str(cmd)]
            for token in cmd_list:
                if "pip" in token or "uv" in token:
                    installer_calls.append(cmd_list)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with mock.patch("subprocess.run", side_effect=spy_run):
            try:
                provision_environment(root, "0" * 40, root, sbx_plan=sbx)
                pytest.fail("Expected VerifyRefusalError")
            except VerifyRefusalError as exc:
                code = getattr(getattr(exc, "reason", None), "code", "")
                assert code == "dependency_bearing" or "dependency" in str(exc).lower()

        assert len(installer_calls) == 0, f"Installer was invoked: {installer_calls}"


def test_setup_py_hook_never_runs_on_host():
    from jittest.env import provision_environment
    from jittest.sandbox import SandboxPlan
    from jittest.verify import VerifyRefusalError

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir).resolve()
        canary = root / "canary.txt"
        (root / "setup.py").write_text(
            f"import pathlib\npathlib.Path({str(canary)!r}).write_text('CANARY')\n"
            "from setuptools import setup\nsetup(name='evil', version='0.1', install_requires=['dep'])\n",
            encoding="utf-8",
        )
        sbx = SandboxPlan(backend="docker", image="python:3.13-slim")
        sbx.mode = "required"

        with contextlib.suppress(VerifyRefusalError):
            provision_environment(root, "0" * 40, root, sbx_plan=sbx)

        assert not canary.exists(), "Candidate setup.py was executed on the host!"
