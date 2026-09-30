"""Real Git/Action/CLI filename contracts using only owned harmless fixtures."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest import action
from jittest.receipt import _seed_to_pem, verify_receipt

ROOT = Path(__file__).resolve().parents[1]


def platform_env():
    names = ('PATH', 'SystemRoot', 'SYSTEMROOT', 'COMSPEC', 'PATHEXT', 'USERPROFILE',
             'HOMEDRIVE', 'HOMEPATH', 'TEMP', 'TMP', 'HOME')
    return {name: os.environ[name] for name in names if name in os.environ}


class FilenameContract(unittest.TestCase):
    def make_pair(self, root, name):
        repo = root / 'repo'
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args],
                                           env=platform_env(), stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q')
        git('config', 'user.name', 'Harmless Filename Fixture')
        git('config', 'user.email', 'fixture@example.invalid')
        git('config', 'core.quotepath', 'true')
        git('remote', 'add', 'origin', 'https://github.com/jittest-fixtures/filename-contract.git')
        (repo / 'app.py').write_bytes(b'def value():\n    return 1\n')
        test = repo / name
        test.write_bytes(b'from app import value\ndef test_value():\n    assert value() == 1\n')
        git('add', '.')
        git('commit', '-qm', 'base')
        base = git('rev-parse', 'HEAD')
        (repo / 'app.py').write_bytes(b'def value():\n    return 2\n')
        test.write_bytes(test.read_bytes() + b'# changed own test\n')
        git('commit', '-qam', 'head')
        return repo, base, git('rev-parse', 'HEAD'), test

    def test_unicode_filename_survives_real_git(self):
        with tempfile.TemporaryDirectory() as d:
            repo, base, head, _ = self.make_pair(Path(d), 'test_café.py')
            files = action.get_changed_files(repo, base, head)
            self.assertIn('test_café.py', files)
            self.assertEqual([f for f in files if action.is_test_file(f)], ['test_café.py'])

    @unittest.skipIf(os.name == 'nt', 'Windows forbids control characters in filenames')
    def test_newline_filename_survives_real_git(self):
        with tempfile.TemporaryDirectory() as d:
            repo, base, head, _ = self.make_pair(Path(d), 'test_line\nbreak.py')
            files = action.get_changed_files(repo, base, head)
            self.assertEqual([f for f in files if action.is_test_file(f)], ['test_line\nbreak.py'])

    def run_entrypoint(self, entrypoint, name):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            repo, base, head, test = self.make_pair(root, name)
            bootstrap = root / 'bootstrap'
            bootstrap.mkdir()
            # Only external comment publication is intercepted. Real diff,
            # provisioning, worktrees, mini runner, signing/consumer and policy.
            (bootstrap / 'sitecustomize.py').write_text(
                'import jittest.action, jittest.github\n'
                'jittest.action.upsert_pr_comment = lambda *a, **kw: "owned fixture"\n'
                'jittest.github.upsert_pr_comment = jittest.action.upsert_pr_comment\n')
            key = root / 'PUBLIC_TEST_ONLY.pem'
            key.write_bytes(_seed_to_pem(bytes(range(32))))
            key.chmod(0o600)
            out = root / ('out' if entrypoint == 'jittest.action' else 'jittest-evidence')
            summary = root / 'summary.md'
            env = {**platform_env(), 'HOME': str(root), 'USERPROFILE': str(root),
                   'PYTHONPATH': str(bootstrap) + os.pathsep + str(ROOT / 'src'),
                   'JITTEST_FORCE_MINIRUNNER': '1', 'JITTEST_REPO_PATH': str(repo),
                   'JITTEST_BASE': base, 'JITTEST_HEAD': head, 'JITTEST_POLICY': 'strict',
                   'JITTEST_SANDBOX_MODE': 'off', 'GITHUB_EVENT_NAME': 'push',
                   'JITTEST_SIGNING_KEY_PATH': str(key), 'JITTEST_OUTPUT_DIR': str(out),
                   'GITHUB_STEP_SUMMARY': str(summary)}
            command = [sys.executable, '-m', entrypoint]
            if entrypoint == 'jittest.cli':
                command += ['action', '--repo', str(repo), '--sandbox', 'off']
            result = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                    text=True, encoding='utf-8', timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipts = list(out.glob('evidence-*.json'))
            self.assertEqual(len(receipts), 1, result.stdout + result.stderr)
            receipt = json.loads(receipts[0].read_text(encoding='utf-8'))
            self.assertTrue(receipt['proven_catch'])
            result = verify_receipt(receipt, expected_base=base, expected_head=head,
                                    expected_test_sha256=hashlib.sha256(test.read_bytes()).hexdigest(),
                                    expected_signer='03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8',
                                    strict_signer=True,
                                    expected_repo='github.com/jittest-fixtures/filename-contract')
            self.assertTrue(result.valid, str(result))
            self.assertNotIn('Zero test files modified', summary.read_text(encoding='utf-8'))

    def test_actual_action_unicode_receipt(self):
        self.run_entrypoint('jittest.action', 'test_café.py')

    def test_actual_cli_unicode_receipt(self):
        self.run_entrypoint('jittest.cli', 'test_café.py')

    @unittest.skipIf(os.name == 'nt', 'Windows forbids control characters in filenames')
    def test_actual_action_newline_receipt(self):
        self.run_entrypoint('jittest.action', 'test_line\nbreak.py')

    @unittest.skipIf(os.name == 'nt', 'invalid filename bytes only supported on POSIX')
    def test_invalid_filesystem_bytes_refuse_comparison(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            repo, base, _, _ = self.make_pair(root, 'test_ok.py')
            raw = os.fsencode(repo) + b'/test_\xff.py'
            with open(raw, 'wb') as f:
                f.write(b'# own harmless invalid-byte filename\n')
            subprocess.run(['git', '-C', str(repo), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(repo), 'commit', '-qm', 'invalid filename'], check=True)
            head = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD']).decode().strip()
            with self.assertRaises(UnicodeDecodeError):
                action.get_changed_files(repo, base, head)
            env = {**platform_env(), 'JITTEST_BASE': base, 'JITTEST_HEAD': head,
                   'GITHUB_EVENT_NAME': 'push'}
            out = root / 'out'
            with patch.dict(os.environ, env, clear=True), patch.object(action, '_report_summary', return_value='owned fixture'):
                status = action.run_action(repo, policy='strict', sandbox_override='off', output_dir=out)
            self.assertEqual(status, 1)
            data = json.loads((out / 'comparison-refusal.json').read_text())
            self.assertFalse(data['denominator_known'])
