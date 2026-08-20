import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest.action import run_action
from jittest.diff import git_env
from jittest.execute import Disposition
from jittest.verify import VerdictClass, verify_test


class SevenFixturesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jt_fix7_"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=self.repo, check=True, capture_output=True, env=git_env())
        subprocess.run(["git", "config", "user.name", "test"], cwd=self.repo, check=True, env=git_env())
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo, check=True, env=git_env())
        subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=self.repo, check=True, env=git_env())

    def tearDown(self):
        def _onerror(func, path, exc_info):
            import os
            import stat
            os.chmod(path, stat.S_IWRITE)
            func(path)
        shutil.rmtree(self.tmp, onerror=_onerror)

    def _commit(self, files: dict[str, str], msg: str) -> str:
        for rel_p, content in files.items():
            full_p = self.repo / rel_p
            full_p.parent.mkdir(parents=True, exist_ok=True)
            full_p.write_text(content, encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True, env=git_env())
        subprocess.run(["git", "commit", "--allow-empty", "-m", msg], cwd=self.repo, check=True, capture_output=True, env=git_env())
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True, errors="replace", check=True, env=git_env()).stdout.strip()

    def test_fixture_1_regression_catch(self):
        """1. base PASS -> head FAIL, test unchanged => proven_catch (regression)"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "base clean")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a - b\n",  # regression introduced
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head broken")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        self.assertEqual(evidence["verdict"], VerdictClass.PROVEN_CATCH)
        self.assertEqual(evidence["disposition"], Disposition.CATCHING)
        self.assertTrue(evidence["proven_catch"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(evidence["base_failure_kind"], "none")

    def test_fixture_2_reproduction_catch(self):
        """2. base FAIL -> head PASS, new test added => reproduction_catch [NEW]"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a - b\n",  # bug on base
        }, "base buggy")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",  # bug fixed on head
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head fixed + new test")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        self.assertEqual(evidence["verdict"], VerdictClass.REPRODUCTION_CATCH)
        self.assertEqual(evidence["disposition"], Disposition.REPRODUCTION_CATCH)
        self.assertTrue(evidence["proven_catch"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(evidence["base_failure_kind"], "assertion")

    def test_fixture_3_non_discriminating_both_pass(self):
        """3. base PASS -> head PASS => non_discriminating"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "base clean")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head clean")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        self.assertEqual(evidence["verdict"], VerdictClass.NON_DISCRIMINATING)
        self.assertEqual(evidence["disposition"], Disposition.HEAD_PASSED)
        self.assertFalse(evidence["proven_catch"])
        self.assertEqual(exit_code, 1)

    def test_fixture_4_inconclusive_both_fail(self):
        """4. base FAIL -> head FAIL => inconclusive / latent failure"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a - b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "base broken")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a - b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head broken")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        self.assertIn(evidence["verdict"], (VerdictClass.INCONCLUSIVE, VerdictClass.REFUTED))
        self.assertFalse(evidence["proven_catch"])
        self.assertEqual(exit_code, 1)

    def test_fixture_5_comment_only_edit(self):
        """5. comment-only test edit, source unchanged => non_discriminating"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "# Comment base\nfrom calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "base with comment")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "# Comment head updated\nfrom calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head with updated comment")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        self.assertEqual(evidence["verdict"], VerdictClass.NON_DISCRIMINATING)
        self.assertEqual(evidence["disposition"], Disposition.HEAD_PASSED)
        self.assertFalse(evidence["proven_catch"])
        self.assertEqual(exit_code, 1)

    def test_fixture_6_import_error_not_a_catch(self):
        """6. base fails via ImportError -> head PASS => base_uncollectable (must NOT be a catch) [NEW]"""
        base_sha = self._commit({
            # Missing helper_module on base
            "calc.py": "def add(a, b):\n    return a + b\n",
        }, "base missing dependency")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "helper_module.py": "VAL = 5\n",
            "tests/test_calc.py": "import helper_module\nfrom calc import add\ndef test_add():\n    assert add(2, 3) == helper_module.VAL\n"
        }, "head added helper_module")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_calc.py",
            sandbox_mode="off",
        )
        # Must NOT be a catch!
        self.assertNotEqual(evidence["verdict"], VerdictClass.REPRODUCTION_CATCH)
        self.assertNotEqual(evidence["verdict"], VerdictClass.PROVEN_CATCH)
        self.assertEqual(evidence["verdict"], VerdictClass.INCONCLUSIVE)
        self.assertEqual(evidence["disposition"], Disposition.BASE_UNCOLLECTABLE)
        self.assertFalse(evidence["proven_catch"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(evidence["base_failure_kind"], "collection")

    def test_fixture_7_sandbox_required_fails_closed(self):
        """7. sandbox-mode: 'required', no container backend => SANDBOX_UNAVAILABLE, exit 1"""
        base_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
        }, "base")
        head_sha = self._commit({
            "calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n"
        }, "head with added test")

        out_dir = self.tmp / "evidence_out"
        out_dir.mkdir()
        old_base = os.environ.get("JITTEST_BASE")
        old_head = os.environ.get("JITTEST_HEAD")
        try:
            os.environ["JITTEST_BASE"] = base_sha
            os.environ["JITTEST_HEAD"] = head_sha
            rc = run_action(
                repo_path=self.repo,
                policy="strict",
                sandbox_override="required",
                output_dir=out_dir,
            )
            self.assertEqual(rc, 1)
        finally:
            if old_base:
                os.environ["JITTEST_BASE"] = old_base
            else:
                os.environ.pop("JITTEST_BASE", None)
            if old_head:
                os.environ["JITTEST_HEAD"] = old_head
            else:
                os.environ.pop("JITTEST_HEAD", None)

    def test_fixture_native_dependency_provisioning(self):
        """8. Target repository with third-party dependency (PyYAML with C/native extensions)."""
        base_sha = self._commit({
            "requirements.txt": "pyyaml>=6.0\n",
            "config_parser.py": "import yaml\ndef parse_val(raw):\n    return yaml.safe_load(raw).get('val', 0)\n",
            "tests/test_cfg.py": "from config_parser import parse_val\ndef test_parse():\n    assert parse_val('val: 42') == 42\n",
        }, "base with pyyaml")
        head_sha = self._commit({
            "requirements.txt": "pyyaml>=6.0\n",
            "config_parser.py": "import yaml\ndef parse_val(raw):\n    return yaml.safe_load(raw).get('val', 0) + 1\n",  # regression
            "tests/test_cfg.py": "from config_parser import parse_val\ndef test_parse():\n    assert parse_val('val: 42') == 42\n",
        }, "head with regression")

        evidence, exit_code = verify_test(
            repo_path=self.repo,
            base_ref=base_sha,
            head_ref=head_sha,
            test_file_path=self.repo / "tests" / "test_cfg.py",
            sandbox_mode="off",
        )
        self.assertEqual(evidence["verdict"], VerdictClass.PROVEN_CATCH)
        self.assertEqual(evidence["disposition"], Disposition.CATCHING)
        self.assertTrue(evidence["proven_catch"])
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
