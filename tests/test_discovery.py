"""Tests for non-executing manifest discovery (Task J1-1).

Verifies that manifest discovery:
1. Never imports or executes candidate files (setup.py, sitecustomize.py, pytest.py, conftest.py, *.pth).
2. Detects packaging kind, build backend, and declared dependencies.
3. Detects symlink escapes outside the worktree.
4. Enforces 1 MiB file read limits.
5. Flags ambiguous build metadata.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jittest.discovery import ManifestReport, discover_manifest


class TestDiscoveryNeverExecutesCandidate(unittest.TestCase):
    def test_discovery_never_executes_candidate(self):
        """Fixture repo whose setup.py, sitecustomize.py, pytest.py, conftest.py, and evil.pth
        each write a canary file. None must exist after discovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve()

            canary_dir = worktree / "canaries"
            canary_dir.mkdir()

            setup_canary = canary_dir / "setup_ran.txt"
            sitecustomize_canary = canary_dir / "sitecustomize_ran.txt"
            pytest_canary = canary_dir / "pytest_ran.txt"
            conftest_canary = canary_dir / "conftest_ran.txt"
            pth_canary = canary_dir / "pth_ran.txt"

            # 1. Hostile setup.py
            (worktree / "setup.py").write_text(
                f"from pathlib import Path\n"
                f"Path({str(setup_canary)!r}).write_text('CANARY_TRIGGERED', encoding='utf-8')\n"
                f"from setuptools import setup\n"
                f"setup(name='fixture_pkg', version='0.1.0', install_requires=['requests>=2.0.0'])\n",
                encoding="utf-8",
            )

            # 2. Hostile sitecustomize.py
            (worktree / "sitecustomize.py").write_text(
                f"from pathlib import Path\n"
                f"Path({str(sitecustomize_canary)!r}).write_text('CANARY_TRIGGERED', encoding='utf-8')\n",
                encoding="utf-8",
            )

            # 3. Hostile pytest.py
            (worktree / "pytest.py").write_text(
                f"from pathlib import Path\n"
                f"Path({str(pytest_canary)!r}).write_text('CANARY_TRIGGERED', encoding='utf-8')\n",
                encoding="utf-8",
            )

            # 4. Hostile conftest.py
            (worktree / "conftest.py").write_text(
                f"from pathlib import Path\n"
                f"Path({str(conftest_canary)!r}).write_text('CANARY_TRIGGERED', encoding='utf-8')\n",
                encoding="utf-8",
            )

            # 5. Hostile evil.pth
            (worktree / "evil.pth").write_text(
                f"import pathlib; pathlib.Path({str(pth_canary)!r}).write_text('CANARY_TRIGGERED')\n",
                encoding="utf-8",
            )

            modules_before = set(sys.modules.keys())

            report = discover_manifest(worktree)

            # Assert no canary files were created
            self.assertFalse(setup_canary.exists(), "setup.py was executed during discovery!")
            self.assertFalse(sitecustomize_canary.exists(), "sitecustomize.py was executed during discovery!")
            self.assertFalse(pytest_canary.exists(), "pytest.py was executed during discovery!")
            self.assertFalse(conftest_canary.exists(), "conftest.py was executed during discovery!")
            self.assertFalse(pth_canary.exists(), "evil.pth was executed during discovery!")

            # Assert no candidate module leaked into sys.modules
            modules_after = set(sys.modules.keys())
            leaked = {m for m in (modules_after - modules_before) if m in ("sitecustomize", "pytest", "conftest", "fixture_pkg")}
            self.assertEqual(leaked, set(), f"Modules leaked into sys.modules: {leaked}")

            # Assert report structure
            self.assertIsInstance(report, ManifestReport)
            self.assertTrue(report.has_setup_py)
            self.assertTrue(report.has_pth_files)
            self.assertTrue(report.has_sitecustomize)
            self.assertTrue(report.has_shadowed_pytest)
            self.assertTrue(report.has_conftest)
            self.assertIn("requests>=2.0.0", report.declared_dependencies)


class TestDiscoveryManifestDetails(unittest.TestCase):
    def test_pyproject_toml_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve()
            (worktree / "pyproject.toml").write_text(
                """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "click>=8.0",
    "pydantic",
]

[project.optional-dependencies]
test = [
    "pytest>=7.0",
]
""",
                encoding="utf-8",
            )
            report = discover_manifest(worktree)
            self.assertEqual(report.packaging_kind, "pyproject")
            self.assertEqual(report.build_backend, "hatchling.build")
            self.assertIn("click>=8.0", report.declared_dependencies)
            self.assertIn("pydantic", report.declared_dependencies)
            self.assertIn("pytest>=7.0", report.declared_dependencies)
            self.assertFalse(report.ambiguous)

    def test_setup_cfg_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve()
            (worktree / "setup.cfg").write_text(
                """
[metadata]
name = demo
version = 0.1.0

[options]
install_requires =
    flask>=2.0
    jinja2
""",
                encoding="utf-8",
            )
            report = discover_manifest(worktree)
            self.assertEqual(report.packaging_kind, "setup_cfg")
            self.assertIn("flask>=2.0", report.declared_dependencies)
            self.assertIn("jinja2", report.declared_dependencies)

    def test_requirements_txt_discovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve()
            (worktree / "requirements.txt").write_text(
                "# comment\nrequests>=2.25.0\n--index-url https://example.com\nurllib3<2.0\n",
                encoding="utf-8",
            )
            report = discover_manifest(worktree)
            self.assertIn("requests>=2.25.0", report.declared_dependencies)
            self.assertIn("urllib3<2.0", report.declared_dependencies)

    def test_symlink_escape_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve() / "repo"
            outside = Path(tmpdir).resolve() / "outside"
            worktree.mkdir()
            outside.mkdir()
            secret_file = outside / "secret.txt"
            secret_file.write_text("secret", encoding="utf-8")

            link_path = worktree / "escape_link.txt"
            try:
                os.symlink(str(secret_file), str(link_path))
                report = discover_manifest(worktree)
                self.assertTrue(len(report.symlink_escapes) > 0)
                self.assertTrue(report.ambiguous)
                self.assertTrue(any("symlink_escape" in r for r in report.reasons))
            except (OSError, NotImplementedError):
                pass  # Covered by test_symlink_escape_detection_mocked below

    def test_symlink_escape_detection_mocked(self):
        from unittest import mock

        from jittest.discovery import _check_symlink_escape

        wt = Path(tempfile.gettempdir()).resolve() / "safe_wt"
        mock_link = mock.MagicMock(spec=Path)
        mock_link.is_symlink.return_value = True
        mock_link.resolve.return_value = Path(tempfile.gettempdir()).resolve() / "outside" / "evil"
        self.assertTrue(_check_symlink_escape(mock_link, wt))

    def test_oversized_manifest_rejected_or_truncated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = Path(tmpdir).resolve()
            # 2 MiB requirements.txt
            large_content = "pytest\n" * (300 * 1024)
            (worktree / "requirements.txt").write_text(large_content, encoding="utf-8")

            report = discover_manifest(worktree)
            self.assertTrue(report.ambiguous)
            self.assertTrue(any("oversized_file" in r or "file_size_exceeded" in r for r in report.reasons))


if __name__ == "__main__":
    unittest.main()
