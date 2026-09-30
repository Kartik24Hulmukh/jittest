"""Harmless isolated Git/archive fixtures for byte-bound build provenance."""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_identity_tests', ROOT / 'build_identity.py')
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


class BuildIdentity(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'src/jittest').mkdir(parents=True)
        (self.root / 'src/jittest/__init__.py').write_bytes(b'# harmless source\n')
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/tool.py').write_bytes(b'# harmless build input\n')
        for name in IDENTITY.ROOT_FILES:
            (self.root / name).write_bytes(b'# harmless input\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Harmless Build Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.commit()

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       env=IDENTITY.git_env(), stderr=subprocess.DEVNULL)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'harmless fixture')

    def identity(self):
        return IDENTITY.build_provenance(self.root)

    def archive(self):
        data = self.identity()
        shutil.rmtree(self.root / '.git')
        (self.root / 'src/jittest/_build_provenance.json').write_text(json.dumps(data))
        return data

    def test_clean_identity_retains_exact_head_and_empty_diff(self):
        data = self.identity()
        self.assertEqual(data['source_sha'], self.git('rev-parse', 'HEAD').decode().strip())
        self.assertEqual(data['working_diff_sha256'], IDENTITY.EMPTY_SHA256)
        self.assertIn('src/jittest/__init__.py', data['build_inputs'])
        self.assertEqual(data, self.identity())

    def test_untracked_source_has_nonempty_distinct_identity(self):
        before = self.identity()
        p = self.root / 'src/jittest/extra.py'
        p.write_bytes(b'# harmless addition\n')
        after = self.identity()
        self.assertEqual(before['source_sha'], after['source_sha'])
        self.assertNotEqual(after['working_diff_sha256'], IDENTITY.EMPTY_SHA256)
        self.assertNotEqual(before['build_inputs_sha256'], after['build_inputs_sha256'])
        p.write_bytes(b'# changed harmless addition\n')
        self.assertNotEqual(after['working_diff_sha256'], self.identity()['working_diff_sha256'])

    def test_ignored_source_cannot_be_false_clean(self):
        (self.root / '.gitignore').write_text('ignored.py\n')
        self.commit()
        (self.root / 'src/jittest/ignored.py').write_bytes(b'# ignored source\n')
        self.assertEqual(self.git('diff', 'HEAD'), b'')
        self.assertNotEqual(self.identity()['working_diff_sha256'], IDENTITY.EMPTY_SHA256)

    def test_deleted_or_changed_tracked_source_is_dirty(self):
        p = self.root / 'src/jittest/__init__.py'
        p.write_bytes(b'# changed source\n')
        self.assertNotEqual(self.identity()['working_diff_sha256'], IDENTITY.EMPTY_SHA256)
        p.unlink()
        self.assertNotEqual(self.identity()['working_diff_sha256'], IDENTITY.EMPTY_SHA256)

    def test_unrelated_untracked_output_does_not_change_identity(self):
        before = self.identity()
        (self.root / 'report.json').write_bytes(b'{}')
        (self.root / 'src/jittest/__pycache__').mkdir()
        (self.root / 'src/jittest/__pycache__/foo.pyc').write_bytes(b'cache')
        (self.root / 'src/jittest/.pytest_cache').mkdir()
        (self.root / 'src/jittest/.pytest_cache/README.md').write_bytes(b'cache')
        self.assertEqual(before, self.identity())

    def test_git_environment_cannot_reassign_source(self):
        before = self.identity()
        with patch.dict(os.environ, {'GIT_DIR': '/nonexistent', 'GIT_WORK_TREE': '/nonexistent',
                                     'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.worktree',
                                     'GIT_CONFIG_VALUE_0': '/nonexistent'}):
            self.assertEqual(before, self.identity())

    def test_clean_archive_preserves_identity(self):
        before = self.archive()
        self.assertEqual(before, self.identity())

    def test_dirty_archive_preserves_identity_not_clean_claim(self):
        (self.root / 'src/jittest/extra.py').write_bytes(b'# harmless dirty build\n')
        before = self.archive()
        self.assertNotEqual(before['working_diff_sha256'], IDENTITY.EMPTY_SHA256)
        self.assertEqual(before, self.identity())

    def test_changed_archive_refuses_stale_identity(self):
        self.archive()
        (self.root / 'src/jittest/__init__.py').write_bytes(b'# changed archive\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.identity()

    def test_added_or_deleted_archive_refuses_stale_identity(self):
        self.archive()
        p = self.root / 'src/jittest/extra.py'
        p.write_bytes(b'# archive addition\n')
        with self.assertRaises(ValueError):
            self.identity()
        p.unlink()
        (self.root / 'build_identity.py').unlink()
        with self.assertRaises(ValueError):
            self.identity()

    def test_old_unbound_archive_refuses(self):
        data = self.archive()
        data.pop('build_inputs')
        data.pop('build_inputs_sha256')
        (self.root / 'src/jittest/_build_provenance.json').write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            self.identity()

    def test_corrupted_manifest_digest_refuses(self):
        data = self.archive()
        data['build_inputs_sha256'] = 'f' * 64
        (self.root / 'src/jittest/_build_provenance.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            self.identity()

    @unittest.skipIf(os.name == 'nt', 'symlink creation requires additional Windows privileges')
    def test_symlink_build_input_refuses(self):
        (self.root / 'src/jittest/link.py').symlink_to('__init__.py')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.identity()

    def test_finished_wheel_bytes_cannot_diverge_from_manifest(self):
        data = self.identity()
        wheel = self.root / 'fixture.whl'
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('jittest/__init__.py', b'# harmless source\n')
        IDENTITY.validate_artifact(wheel, 'wheel', data)
        with zipfile.ZipFile(wheel, 'w') as archive:
            archive.writestr('jittest/__init__.py', b'# substituted runtime bytes\n')
        with self.assertRaisesRegex(ValueError, 'finished artifact'):
            IDENTITY.validate_artifact(wheel, 'wheel', data)

    def test_finished_sdist_missing_helper_or_changed_script_refuses(self):
        data = self.identity()
        archive = self.root / 'fixture.tar.gz'
        def write(omit=None):
            with tarfile.open(archive, 'w:gz') as target:
                for name in data['build_inputs']:
                    if name == omit:
                        continue
                    content = (self.root / name).read_bytes()
                    entry = tarfile.TarInfo('fixture/' + name)
                    entry.size = len(content)
                    target.addfile(entry, io.BytesIO(content))
        write()
        IDENTITY.validate_artifact(archive, 'sdist', data)
        write('build_identity.py')
        with self.assertRaisesRegex(ValueError, 'finished artifact'):
            IDENTITY.validate_artifact(archive, 'sdist', data)
        (self.root / 'scripts/tool.py').write_bytes(b'# substituted build script\n')
        write()
        with self.assertRaisesRegex(ValueError, 'finished artifact'):
            IDENTITY.validate_artifact(archive, 'sdist', data)
