"""Real subprocess SIGINT at the CLI boundary; no provider or network calls."""
import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CliInterrupt(unittest.TestCase):
    def test_only_keyboard_interrupt_is_handled(self):
        with patch('jittest.cli._cmd_verify', side_effect=KeyboardInterrupt), patch('sys.stderr'):
            self.assertEqual(main(['verify', '--test', 'test_fixture.py']), 130)
        for exception in (SystemExit(7), RuntimeError('unchanged')):
            with patch('jittest.cli._cmd_verify', side_effect=exception), self.assertRaises(type(exception)):
                main(['verify', '--test', 'test_fixture.py'])

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX SIGINT delivery')
    def test_real_sigint_preserves_interrupted_journal_and_cleans_worktrees(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / 'repo'
            repo.mkdir()
            tmp = root / 'tmp'
            tmp.mkdir()
            marker = root / 'started'
            env = {name: os.environ[name] for name in ('PATH',) if name in os.environ}
            env.update(HOME=str(root), TMPDIR=str(tmp), PYTHONPATH=str(ROOT / 'src'),
                       PYTHONDONTWRITEBYTECODE='1', JITTEST_FORCE_MINIRUNNER='1',
                       PIP_NO_INDEX='1', UV_OFFLINE='1')

            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args],
                                               env=env, stderr=subprocess.DEVNULL).decode().strip()

            git('init', '-q')
            git('config', 'user.name', 'Owned interrupt fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (repo / 'app.py').write_text('def value():\n    return 1\n')
            test = repo / 'test_wait.py'
            test.write_text('import json,os,subprocess,sys,threading\nfrom pathlib import Path\n'
                            'def test_wait():\n'
                            '    child = subprocess.Popen([sys.executable, "-S", "-c", '
                            '"import threading; threading.Event().wait(60)"])\n'
                            f'    Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n'
                            '    threading.Event().wait(60)\n    assert False\n')
            git('add', '.')
            git('commit', '-qm', 'base')
            base = git('rev-parse', 'HEAD')
            (repo / 'app.py').write_text('def value():\n    return 2\n')
            git('commit', '-qam', 'head')
            head = git('rev-parse', 'HEAD')
            output = root / 'evidence.json'
            command = [sys.executable, '-S', '-m', 'jittest', 'verify', '--repo', str(repo),
                       '--base', base, '--head', head, '--test', 'test_wait.py',
                       '--sandbox-mode', 'off', '--output', str(output)]
            process = subprocess.Popen(command, env=env, cwd=root, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True)
            try:
                deadline = time.monotonic() + 20
                while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                    threading.Event().wait(.01)
                self.assertTrue(marker.exists(), 'candidate must actually begin execution')
                candidate_pids = json.loads(marker.read_text())
                process.send_signal(signal.SIGINT)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 130, (stdout, stderr))
                for candidate_pid in candidate_pids:
                    state = subprocess.run(['ps', '-p', str(candidate_pid), '-o', 'stat='],
                                           capture_output=True, text=True, check=False)
                    # The direct candidate is reaped; an orphaned grandchild
                    # may await PID 1 reaping, but must already be terminated.
                    self.assertTrue(not state.stdout.strip() or state.stdout.strip().startswith('Z'),
                                    f'candidate process {candidate_pid} still running: {state.stdout}')
                self.assertFalse(subprocess.run(['ps', '-p', str(candidate_pids[0]), '-o', 'stat='],
                                                capture_output=True, text=True).stdout.strip(),
                                 'direct candidate must be reaped')
                self.assertNotIn(b'Traceback', stderr)
                self.assertIn(b'jittest: interrupted', stderr)
                self.assertFalse(output.exists(), 'interruption must not manufacture a receipt')
                snapshots = list((root / 'census').glob('*/snapshot.json'))
                self.assertEqual(len(snapshots), 1)
                data = json.loads(snapshots[0].read_text())
                self.assertEqual(data['state'], 'interrupted')
                self.assertEqual(data['candidates'][0]['disposition'], 'interrupted')
                self.assertEqual(data['candidates'][0]['base_sha'], base)
                self.assertEqual(data['candidates'][0]['head_sha'], head)
                self.assertEqual(data['candidates'][0]['candidate_sha256'],
                                 hashlib.sha256(test.read_bytes()).hexdigest())
                journal = snapshots[0].with_name('journal.jsonl').read_bytes()
                self.assertEqual(hashlib.sha256(journal).hexdigest(), data['journal_sha256'])
                self.assertEqual(git('worktree', 'list', '--porcelain').count('worktree '), 1)
                self.assertEqual(list(tmp.iterdir()), [])
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=10)
                if marker.exists():
                    candidate_pid = json.loads(marker.read_text())[0]
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(candidate_pid, signal.SIGKILL)


if __name__ == '__main__':
    unittest.main()
