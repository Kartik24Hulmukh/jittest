"""Real Git regression: nested branch-sync merges are not mainline PRs."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from eval.false_positives import select_pairs


class MainlineSampleTests(unittest.TestCase):
    def test_nested_sync_merge_never_enters_pr_population(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            env.update(GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
                       GIT_AUTHOR_EMAIL='fixture@localhost', GIT_COMMITTER_EMAIL='fixture@localhost',
                       GIT_AUTHOR_DATE='2025-01-01T12:00:00+0000',
                       GIT_COMMITTER_DATE='2025-01-01T12:00:00+0000')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args],
                    env=env, stderr=subprocess.PIPE, text=True).strip()
            git('init', '--quiet', '-b', 'main')
            (repo / 'alpha.py').write_text('def alpha():\n    return 1\n')
            git('add', '.'); git('commit', '--quiet', '-m', 'baseline')
            git('checkout', '--quiet', '-b', 'feature')
            (repo / 'alpha.py').write_text('def alpha():\n    return 2\n')
            git('commit', '--quiet', '-am', 'feature')
            git('checkout', '--quiet', 'main')
            (repo / 'sync.py').write_text('def sync():\n    return 3\n')
            git('add', '.'); git('commit', '--quiet', '-m', 'main advanced')
            base = git('rev-parse', 'HEAD')
            git('checkout', '--quiet', 'feature')
            git('merge', '--quiet', '--no-ff', 'main', '-m', 'Merge branch main into feature')
            head = git('rev-parse', 'HEAD')
            git('checkout', '--quiet', 'main')
            git('merge', '--quiet', '--no-ff', 'feature', '-m', 'Merge pull request #1 from feature')
            pairs, _ = select_pairs(repo, 40, since='2024-01-01', until='2025-12-31')
            self.assertEqual(pairs, [(base, head)])
