"""Remote Action identity regressions; no network or private credentials."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('action_installer', Path(__file__).resolve().parents[1] / 'scripts/install_action.py')
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


class ActionArchiveInstall(unittest.TestCase):
    def test_invalid_remote_identity_never_dispatches(self):
        for repo, ref in [('github.com/owner/repo', 'main'), ('owner/repo', '-option'),
                          ('owner/repo', ''), ('owner/repo', '../branch')]:
            with self.subTest(repo=repo, ref=ref), patch.object(INSTALLER.subprocess, 'run') as run:
                with self.assertRaises(ValueError):
                    INSTALLER.fetch_action_source(repo, ref, Path('/unused'))
                run.assert_not_called()

    def test_archive_mismatch_and_extra_executable_refuse(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / 'archive', Path(temp) / 'checkout'
            for root in (a, b):
                (root / 'src/jittest').mkdir(parents=True)
                (root / 'src/jittest/verify.py').write_bytes(b'# original\n')
            INSTALLER.reconcile_archive(a, b)
            (a / 'src/jittest/verify.py').write_bytes(b'# mutated\n')
            with self.assertRaises(ValueError):
                INSTALLER.reconcile_archive(a, b)
            (a / 'src/jittest/verify.py').write_bytes(b'# original\n')
            (a / 'src/jittest/extra.py').write_bytes(b'# extra\n')
            with self.assertRaises(ValueError):
                INSTALLER.reconcile_archive(a, b)

    def test_identity_helper_must_match_remote_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / 'archive', Path(temp) / 'checkout'
            a.mkdir()
            b.mkdir()
            for root in (a, b):
                (root / 'build_identity.py').write_bytes(b'# reviewed helper\n')
            INSTALLER.reconcile_archive(a, b)
            (a / 'build_identity.py').write_bytes(b'# changed helper\n')
            with self.assertRaises(ValueError):
                INSTALLER.reconcile_archive(a, b)
            (a / 'build_identity.py').unlink()
            with self.assertRaises(ValueError):
                INSTALLER.reconcile_archive(a, b)

    def test_failed_fetch_or_mismatch_never_installs(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(INSTALLER, 'fetch_action_source', side_effect=subprocess.CalledProcessError(128, 'git')), patch.object(INSTALLER.subprocess, 'run') as run:
            with self.assertRaises(subprocess.CalledProcessError):
                INSTALLER.install_action(Path(temp), 'owner/repo', 'main', 'python')
            run.assert_not_called()

    def test_local_checkout_uses_only_its_source(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(INSTALLER.subprocess, 'run') as run, patch.object(INSTALLER, 'fetch_action_source') as fetch:
            source = Path(temp)
            (source / '.git').mkdir()
            INSTALLER.install_action(source, '', '', 'fixture-python')
            fetch.assert_not_called()
            self.assertEqual(run.call_args.args[0], ['fixture-python', '-m', 'pip', 'install', str(source.resolve())])
