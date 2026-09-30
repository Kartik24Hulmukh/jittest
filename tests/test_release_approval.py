"""Offline adversarial release approval cases; no providers or remote writes."""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('release_approval', ROOT / 'scripts/check_release_approval.py')
APPROVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(APPROVAL)


class ReleaseApproval(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dist = self.root / 'dist'
        self.dist.mkdir()
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "0.4.1"\n')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Harmless Release Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('add', 'pyproject.toml')
        self.git('commit', '-qm', 'fixture')
        self.git('tag', 'v0.4.1')
        self.sha = self.git('rev-parse', 'HEAD')
        env = {'GITHUB_SHA': self.sha, 'GITHUB_REF': 'refs/tags/v0.4.1',
               'GITHUB_REPOSITORY': 'fixture/project', 'GITHUB_EVENT_NAME': 'push',
               'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_WORKFLOW_REF': 'fixture/project/.github/workflows/release.yml@refs/tags/v0.4.1'}
        self.env = patch.dict(os.environ, env)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.artifacts = {}
        for name in ('jittest-0.4.1-py3-none-any.whl', 'jittest-0.4.1.tar.gz'):
            data = b'harmless exact artifact fixture'
            (self.dist / name).write_bytes(data)
            self.artifacts[name] = hashlib.sha256(data).hexdigest()
        self.candidate = {'version': '0.4.1', 'source_sha': self.sha,
                          'working_diff_sha256': APPROVAL.EMPTY_SHA256,
                          'artifacts': self.artifacts}
        self.write_candidate()
        self.digest = APPROVAL.create(self.dist, self.root, '1')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args],
                                       env={**APPROVAL.os.environ, 'GIT_CONFIG_GLOBAL': os.devnull,
                                            'GIT_CONFIG_NOSYSTEM': '1'},
                                       stderr=subprocess.DEVNULL).decode().strip()

    def write_candidate(self):
        (self.dist / 'candidate-manifest.json').write_text(json.dumps(self.candidate))

    def verify(self, digest=None, attempt='1', effect='pypi'):
        return APPROVAL.verify(self.dist, self.root, attempt,
                               self.digest if digest is None else digest, effect)

    def edit_approval(self, change):
        path = self.dist / APPROVAL.APPROVAL_NAME
        data = json.loads(path.read_bytes())
        change(data)
        path.write_text(json.dumps(data))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_exact_approved_release_all_effects(self):
        for effect in APPROVAL.EFFECTS:
            self.assertEqual(self.verify(effect=effect), self.digest)

    def test_missing_wrong_and_repo_only_approval_refused(self):
        for digest in ('', '0' * 64, self.digest.upper(), 'not-a-digest'):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.verify(digest=digest)

    def test_raw_manifest_not_canonicalized(self):
        path = self.dist / APPROVAL.APPROVAL_NAME
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ValueError):
            self.verify()

    def test_raw_candidate_bytes_bound_including_census_additions(self):
        path = self.dist / 'candidate-manifest.json'
        for extra in (b' ',):
            path.write_bytes(path.read_bytes() + extra)
            with self.assertRaises(ValueError):
                self.verify()
        self.candidate['future_census'] = {'test_count': 999}
        self.write_candidate()
        with self.assertRaises(ValueError):
            self.verify()

    def test_artifact_tamper_and_extra_inventory_refused(self):
        path = self.dist / next(iter(self.artifacts))
        before = path.read_bytes()
        path.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.verify()
        path.write_bytes(before)
        (self.dist / 'extra.whl').write_bytes(b'extra')
        with self.assertRaises(ValueError):
            self.verify()

    def test_candidate_source_version_dirty_and_path_escape_refused(self):
        for key, value in (('source_sha', 'f' * 40), ('version', '0.4.2'),
                           ('working_diff_sha256', '0' * 64),
                           ('artifacts', {'../escape.whl': '0' * 64, 'a.tar.gz': '0' * 64})):
            before = self.candidate.copy()
            self.candidate[key] = value
            self.write_candidate()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify()
            self.candidate = before
            self.write_candidate()

    def test_execution_context_drift_refused(self):
        for key, value in (('GITHUB_SHA', 'f' * 40), ('GITHUB_REF', 'refs/tags/v0.4.2'),
                           ('GITHUB_REPOSITORY', 'other/project'), ('GITHUB_RUN_ID', '124'),
                           ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                           ('GITHUB_WORKFLOW_REF', 'different/workflow')):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), self.assertRaises(ValueError):
                self.verify()
        with self.assertRaises(ValueError):
            self.verify(attempt='2')

    def test_rerun_downstream_uses_original_build_attempt(self):
        with patch.dict(os.environ, {'GITHUB_RUN_ATTEMPT': '2'}):
            self.assertEqual(self.verify(attempt='1'), self.digest)
            with self.assertRaises(ValueError):
                self.verify(attempt='2')

    def test_source_tree_and_unknown_field_refused_even_with_new_digest(self):
        for key, value in (('source_tree', '0' * 40), ('extra', 'not allowed')):
            self.digest = APPROVAL.create(self.dist, self.root, '1')
            digest = self.edit_approval(lambda d, key=key, value=value: d.update({key: value}))
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(digest=digest)

    def test_explicit_effects_not_truthy_or_inferred(self):
        for value in (1, 'true', None, False):
            self.digest = APPROVAL.create(self.dist, self.root, '1')
            digest = self.edit_approval(lambda d, value=value: d['effects'].update(pypi=value))
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.verify(digest=digest)

    def test_approval_may_narrow_but_not_infer_effects(self):
        digest = self.edit_approval(lambda d: d['effects'].update(floating_v0=False))
        self.verify(digest=digest, effect='pypi')
        with self.assertRaises(ValueError):
            self.verify(digest=digest, effect='floating_v0')
        digest = self.edit_approval(lambda d: d['effects'].pop('github_release'))
        with self.assertRaises(ValueError):
            self.verify(digest=digest)

    def test_dispatch_against_tag_or_branch_never_publishes(self):
        for ref in ('refs/tags/v0.4.1', 'refs/heads/main'):
            with self.subTest(ref=ref), patch.dict(os.environ, {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': ref}):
                digest = APPROVAL.create(self.dist, self.root, '1')
                for effect in APPROVAL.EFFECTS:
                    with self.assertRaises(ValueError):
                        self.verify(digest=digest, effect=effect)

    def test_prerelease_cannot_advance_floating_v0(self):
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "0.4.2rc1"\n')
        self.git('add', 'pyproject.toml')
        self.git('commit', '-qm', 'prerelease fixture')
        self.git('tag', 'v0.4.2rc1')
        self.candidate.update(version='0.4.2rc1', source_sha=self.git('rev-parse', 'HEAD'))
        self.write_candidate()
        with patch.dict(os.environ, {'GITHUB_SHA': self.candidate['source_sha'], 'GITHUB_REF': 'refs/tags/v0.4.2rc1'}):
            digest = APPROVAL.create(self.dist, self.root, '1')
            self.verify(digest=digest, effect='pypi')
            with self.assertRaises(ValueError):
                self.verify(digest=digest, effect='floating_v0')

    def test_strict_json_duplicates_nonfinite_overflow_and_nonobject(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":{"nested":1,"nested":2}}',
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b'{"x":1e999}', b'{"x":-1e999}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                APPROVAL.strict_json(raw)

    def test_signed_digest_does_not_make_nonfinite_json_acceptable(self):
        path = self.dist / APPROVAL.APPROVAL_NAME
        path.write_bytes(b'{"effects":{"pypi":NaN}}')
        with self.assertRaises(ValueError):
            self.verify(digest=hashlib.sha256(path.read_bytes()).hexdigest())


class WorkflowApproval(unittest.TestCase):
    def test_protected_environment_and_recheck_before_every_effect(self):
        text = (ROOT / '.github/workflows/release.yml').read_text()
        for job, effect, marker in (
                ('publish', 'pypi', 'pypa/gh-action-pypi-publish@'),
                ('github-release', 'github_release', 'softprops/action-gh-release@'),
                ('update-floating-tag', 'floating_v0', 'git push origin v0 --force')):
            body = re.split(r'\n  [a-zA-Z_-]+:\n', text.split(f'\n  {job}:\n', 1)[1], maxsplit=1)[0]
            self.assertIn('environment: pypi', body)
            self.assertIn('github.event_name == \'push\' && startsWith(github.ref, \'refs/tags/v', body)
            self.assertIn('actions/download-artifact@', body)
            self.assertIn('vars.JITTEST_RELEASE_APPROVAL_SHA256', body)
            self.assertIn('--build-attempt "$BUILD_ATTEMPT"', body)
            self.assertLess(body.index(f'--effect {effect}'), body.index(marker))
        self.assertIn('needs: [verify-published, github-release]', text)
        self.assertIn("if: steps.release-channel.outputs.stable == 'true'", text)

    def test_build_generates_but_does_not_consume_external_approval(self):
        body = (ROOT / '.github/workflows/release.yml').read_text().split('\n  publish:\n')[0]
        self.assertIn('--create --build-attempt "$BUILD_ATTEMPT"', body)
        self.assertNotIn('vars.JITTEST_RELEASE_APPROVAL_SHA256', body)
