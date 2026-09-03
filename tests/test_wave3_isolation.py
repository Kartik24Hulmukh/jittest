"""Regression tests for Wave 3 defects D1, D2, and D8.

- D2: Dependency provisioning runs with a scrubbed environment (no GITHUB_TOKEN or secrets leaked to setup.py).
- D1: Option D restricted container isolation refuses dependency-bearing tests with clear refusal error.
- D8: Action defaults and artifact upload behavior skew.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest.env import _scrubbed_installer_env, provision_environment
from jittest.sandbox import SandboxPlan
from jittest.verify import VerifyRefusalError, verify_test


class TestWave3D2ProvisioningSanitization(unittest.TestCase):
    def test_scrubbed_env_strips_sensitive_keys(self):
        test_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "GITHUB_TOKEN": "ghp_super_secret_token_12345",
            "GH_TOKEN": "ghp_another_token",
            "AWS_SECRET_ACCESS_KEY": "super_secret_key",
            "NPM_TOKEN": "secret_npm_token",
            "DATABASE_PASSWORD": "secret_password",
            "AUTH_BEARER": "bearer_token",
            "SAFE_SYSTEM_VAR": "harmless_value",
        }
        with mock.patch.dict(os.environ, test_env, clear=True):
            scrubbed = _scrubbed_installer_env()
            self.assertNotIn("GITHUB_TOKEN", scrubbed)
            self.assertNotIn("GH_TOKEN", scrubbed)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", scrubbed)
            self.assertNotIn("NPM_TOKEN", scrubbed)
            self.assertNotIn("DATABASE_PASSWORD", scrubbed)
            self.assertNotIn("AUTH_BEARER", scrubbed)
            self.assertIn("PATH", scrubbed)

    def test_job_f_hostile_setup_does_not_see_github_token(self):
        """Job F hostile fixture: setup.py attempts to read GITHUB_TOKEN."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            # Initialize git repo
            subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo), check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo), check=True)

            # Create hostile setup.py
            hostile_setup = (
                "import os\n"
                "from setuptools import setup\n"
                "if 'GITHUB_TOKEN' in os.environ:\n"
                "    raise RuntimeError('HOSTILE_PROVISIONING_LEAK: GITHUB_TOKEN visible in setup.py!')\n"
                "setup(name='fixture_pkg', version='0.1.0', py_modules=['mod'])\n"
            )
            (repo / "setup.py").write_text(hostile_setup, encoding="utf-8")
            (repo / "mod.py").write_text("X = 1\n", encoding="utf-8")

            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo), check=True, capture_output=True)
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=str(repo), check=True, capture_output=True, text=True
            ).stdout.strip()

            # Run provisioning with GITHUB_TOKEN present in outer process
            with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_forbidden_leak_12345"}):
                result = provision_environment(repo, rev, repo)
                self.assertTrue(Path(result["python_path"]).exists())


class _Worktree:
    def __init__(self, repo, rev):
        self.repo = repo

    def __enter__(self):
        return self.repo

    def __exit__(self, *args):
        pass


class TestWave3D1IsolationContract(unittest.TestCase):
    def test_container_mode_refuses_dependency_bearing_repo(self):
        """Option D: docker/podman refuses dependency-bearing tests rather than silently discarding venv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            test_file = repo / "test_dep.py"
            test_file.write_text("import pytest\ndef test_x(): assert True\n", encoding="utf-8")

            docker_plan = SandboxPlan(backend="docker", image="python:3.13-slim")

            with (
                mock.patch("jittest.verify.resolve_revision", side_effect=["a" * 40, "b" * 40]),
                mock.patch("jittest.verify.plan_sandbox", return_value=docker_plan),
                mock.patch("jittest.verify.Worktree", _Worktree),
                mock.patch("jittest.verify.provision_environment", return_value={
                    "python_path": sys.executable,
                    "lockfile_sha256": "abcdef" * 10,
                    "resolved_versions": {"pytest": "8.0.0"},
                }),
            ):
                with self.assertRaises(VerifyRefusalError) as ctx:
                    verify_test(repo, "HEAD~1", "HEAD", test_file, sandbox_mode="required")
                self.assertIn("isolation contract cannot import project dependencies", str(ctx.exception))


class TestWave3D8ActionDefaultsAndHygiene(unittest.TestCase):
    def test_action_yaml_defaults(self):
        action_path = Path(__file__).resolve().parent.parent / "action.yml"
        self.assertTrue(action_path.exists())
        text = action_path.read_text(encoding="utf-8")

        # Verify sandbox-mode defaults to auto
        self.assertIn("sandbox-mode:", text)
        self.assertIn("default: 'auto'", text)

        # Check artifact upload step warns if missing per contract
        self.assertIn("uses: actions/upload-artifact", text)
        self.assertIn("if-no-files-found: warn", text)


if __name__ == "__main__":
    unittest.main()