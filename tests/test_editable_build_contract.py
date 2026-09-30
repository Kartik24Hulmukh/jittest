"""Editable source is live Git, not an immutable normal-wheel provenance claim."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('editable_identity', ROOT / 'build_identity.py')
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)
HAS_BACKEND = importlib.util.find_spec('hatchling') is not None and importlib.util.find_spec('editables') is not None


class EditablePointerContract(unittest.TestCase):
    def test_only_expected_live_source_pointer_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'src').mkdir()
            wheel = root / 'editable.whl'
            expected = str((root / 'src').resolve())
            for pointer in (expected, expected + '\nimport os', 'import os',
                            str(root / 'other'), expected + '\n' + str(root / 'other'),
                            'src'):
                with self.subTest(pointer=pointer):
                    with zipfile.ZipFile(wheel, 'w') as archive:
                        archive.writestr('_editable_impl_jittest.pth', pointer)
                    if pointer == expected:
                        IDENTITY.validate_editable_artifact(wheel, root)
                    else:
                        previous_cwd = Path.cwd()
                        try:
                            if pointer == 'src':
                                os.chdir(root)
                                self.assertEqual(Path(pointer).resolve(), (root / 'src').resolve())
                            with self.assertRaises(ValueError):
                                IDENTITY.validate_editable_artifact(wheel, root)
                        finally:
                            os.chdir(previous_cwd)

    def test_copied_runtime_frozen_identity_and_import_helpers_refuse(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'src').mkdir()
            wheel = root / 'editable.whl'
            for extra in ('jittest/__init__.py', 'jittest/_build_provenance.json',
                          '_editable_impl_jittest.py', 'extra.pth'):
                with self.subTest(extra=extra):
                    with zipfile.ZipFile(wheel, 'w') as archive:
                        archive.writestr('_editable_impl_jittest.pth', str((root / 'src').resolve()))
                        archive.writestr(extra, '# harmless unwanted fixture')
                    with self.assertRaises(ValueError):
                        IDENTITY.validate_editable_artifact(wheel, root)


@unittest.skipUnless(HAS_BACKEND, 'real build fixture requires optional Hatchling/editables development tools')
class ActualEditableBuild(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.root = self.work / 'source'
        self.root.mkdir()
        shutil.copytree(ROOT / 'src', self.root / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in IDENTITY.ROOT_FILES:
            if (ROOT / name).is_file():
                shutil.copyfile(ROOT / name, self.root / name)
        shutil.copyfile(ROOT / '.gitignore', self.root / '.gitignore')
        self.env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SystemRoot', 'SYSTEMROOT',
                    'COMSPEC', 'PATHEXT', 'TEMP', 'TMP', 'HOME', 'USERPROFILE')}
        self.env['HOME'] = str(self.work)
        self.env['USERPROFILE'] = str(self.work)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Harmless Editable Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        # This owned fixture commits its exact bytes, including any CRLF bytes;
        # production byte identity rules are not relaxed for checkout transforms.
        self.git('config', 'core.autocrlf', 'false')
        self.git('add', '.')
        self.git('commit', '-qm', 'owned editable fixture')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], env=self.env,
                                       stderr=subprocess.DEVNULL).decode().strip()

    def builder(self):
        from hatchling.builders.wheel import WheelBuilder
        out = self.work / 'dist'
        out.mkdir(exist_ok=True)
        return list(WheelBuilder(str(self.root)).build(directory=str(out), versions=['editable']))

    def test_real_hatch_and_pip_editable_keep_live_source_identity(self):
        files = self.builder()
        self.assertEqual(len(files), 1)
        with zipfile.ZipFile(files[0]) as archive:
            self.assertNotIn('jittest/_build_provenance.json', archive.namelist())
        target = self.work / 'site'
        install = subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index',
                                  '--no-deps', '--no-build-isolation', '--target', str(target),
                                  '--editable', str(self.root)], cwd=self.work, env=self.env,
                                 capture_output=True, text=True, timeout=90)
        self.assertEqual(install.returncode, 0, install.stderr[-2000:])
        def probe():
            script = ('import site,sys,json; site.addsitedir(sys.argv[1]); '
                      'import jittest.verify as v; '
                      'print(json.dumps({"sha":v._jittest_version_and_sha()[1],'
                      '"embedded":v._embedded_build_provenance(),'
                      '"dirty":v._get_git_dirty(v.Path(v.__file__).resolve().parents[2]),'
                      '"path":v.__file__}))')
            result = subprocess.run([sys.executable, '-c', script, str(target)], cwd=self.work,
                                    env=self.env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        initial = probe()
        self.assertEqual(initial['sha'], self.git('rev-parse', 'HEAD'))
        self.assertIsNone(initial['embedded'])
        self.assertFalse(initial['dirty'])
        self.assertTrue(Path(initial['path']).is_relative_to(self.root))
        source = self.root / 'src/jittest/__init__.py'
        source.write_bytes(source.read_bytes() + b'\n# own harmless live editable change\n')
        changed = probe()
        self.assertEqual(changed['sha'], initial['sha'])
        self.assertTrue(changed['dirty'])
        self.assertIsNone(changed['embedded'])

    def test_gitless_archive_or_source_embedded_provenance_refuses_editable(self):
        archived = self.root / 'src/jittest/_build_provenance.json'
        archived.write_text(json.dumps(IDENTITY.git_provenance(self.root)))
        with self.assertRaisesRegex(ValueError, 'editable builds require own Git'):
            self.builder()
        (self.root / '.git').rename(self.root / '.fixture-git-metadata')
        with self.assertRaisesRegex(ValueError, 'editable builds require own Git'):
            self.builder()
