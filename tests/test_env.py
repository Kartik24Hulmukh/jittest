"""Unit tests for environment provisioning, preflight checks, and loud failure reporting."""

import tempfile
from pathlib import Path

from jittest.env import EnvSetupError, _compute_lockfile_hash, get_venv_python


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
