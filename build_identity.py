"""Byte-bound build identity shared by packaging and distributable acceptance.

Git HEAD is an attribution, not an assertion that arbitrary working bytes match
it. The manifest binds build inputs including untracked files; an archive must
carry and satisfy that manifest before retaining its original attribution.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

ROOT_FILES = ('pyproject.toml', 'hatch_build.py', 'build_identity.py', 'action.yml',
              'README.md', 'LICENSE', 'CHANGELOG.md')
BUILD_DIRS = ('src', 'scripts')
EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()


def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
    return env


def is_build_input(name: str) -> bool:
    parts = Path(name).parts
    if any(part in {'__pycache__', '.pytest_cache', '.ruff_cache', '.mypy_cache'} for part in parts) or name.endswith(('.pyc', '.pyo')):
        return False
    if name == 'src/jittest/_build_provenance.json':
        return False  # Generated identity cannot recursively hash itself.
    return name in ROOT_FILES or bool(parts and parts[0] in BUILD_DIRS)


def source_manifest(root: Path) -> dict[str, str]:
    manifest = {}
    for name in (*ROOT_FILES, *BUILD_DIRS):
        target = root / name
        if target.is_symlink():
            raise ValueError('build inputs cannot be symlinks')
        paths = target.rglob('*') if target.is_dir() else (target,)
        for path in paths:
            relative = path.relative_to(root).as_posix()
            if not is_build_input(relative):
                continue
            if path.is_symlink():
                raise ValueError('build inputs cannot be symlinks')
            if path.is_file():
                manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(manifest.items()))


def _git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(['git', '-C', str(root), *args], env=git_env(),
                                   stderr=subprocess.PIPE, timeout=30)


def _head_manifest(root: Path) -> dict[str, str]:
    # Use Git's committed bytes, never its index/stat cache or a textual diff.
    names = _git(root, 'ls-tree', '-z', '--name-only', 'HEAD').decode().split('\0')
    selected = [name for name in names if name in (*ROOT_FILES, *BUILD_DIRS)]
    if not selected:
        raise ValueError('Git HEAD lacks build inputs')
    raw = _git(root, 'archive', '--format=tar', 'HEAD', '--', *selected)
    manifest = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            if not is_build_input(member.name):
                continue
            if member.issym() or member.islnk():
                raise ValueError('committed build inputs cannot be symlinks')
            if member.isfile():
                stream = archive.extractfile(member)
                if stream is None:
                    raise ValueError('missing committed build input')
                manifest[member.name] = hashlib.sha256(stream.read()).hexdigest()
    return dict(sorted(manifest.items()))


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def git_provenance(root: Path) -> dict:
    top = Path(_git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve()
    if top != root.resolve():
        raise ValueError('build must use its own Git repository')
    sha = _git(root, 'rev-parse', 'HEAD').decode().strip()
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('invalid build source SHA')
    manifest = source_manifest(root)
    head = _head_manifest(root)
    diff = _git(root, 'diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD')
    # Retain the existing clean sentinel. Any tracked diff or byte-level build
    # addition/deletion/change (including ignored inputs) makes this nonempty.
    material = b'' if not diff and manifest == head else _canonical({
        'tracked_diff_sha256': hashlib.sha256(diff).hexdigest(),
        'head_build_inputs': head, 'working_build_inputs': manifest,
    })
    return {'source_sha': sha, 'working_diff_sha256': hashlib.sha256(material).hexdigest(),
            'build_inputs_sha256': hashlib.sha256(_canonical(manifest)).hexdigest(),
            'build_inputs': manifest}


def validate_manifest(manifest: dict[str, str], provenance: object) -> dict:
    if not isinstance(provenance, dict):
        raise ValueError('invalid archived build provenance')
    for key, length in (('source_sha', 40), ('working_diff_sha256', 64), ('build_inputs_sha256', 64)):
        value = provenance.get(key)
        if not isinstance(value, str) or not re.fullmatch(rf'[0-9a-f]{{{length}}}', value):
            raise ValueError(f'invalid or unbound archived {key}; rebuild from identified Git source')
    recorded = provenance.get('build_inputs')
    if not isinstance(recorded, dict) or not recorded:
        raise ValueError('archive lacks byte-bound build inputs; rebuild from identified Git source')
    if recorded != manifest:
        raise ValueError('archived build inputs changed; refusing stale source identity')
    if provenance['build_inputs_sha256'] != hashlib.sha256(_canonical(manifest)).hexdigest():
        raise ValueError('archived build input manifest digest mismatch')
    return provenance


def validate_archive(root: Path, provenance: object) -> dict:
    return validate_manifest(source_manifest(root), provenance)


def build_provenance(root: Path) -> dict:
    if (root / '.git').exists():
        return git_provenance(root)
    archived = root / 'src/jittest/_build_provenance.json'
    if archived.is_file():
        return validate_archive(root, json.loads(archived.read_text(encoding='utf-8')))
    raise ValueError('build requires Git source identity or byte-bound archived build provenance')


def validate_artifact(artifact: Path, target: str, provenance: dict) -> None:
    """Bind finished artifact bytes too, not only the pre-build working tree."""
    import zipfile
    recorded = provenance['build_inputs']
    actual = {}
    if target == 'wheel':
        expected = {name.removeprefix('src/'): digest for name, digest in recorded.items()
                    if name.startswith('src/jittest/')}
        with zipfile.ZipFile(artifact) as archive:
            for name in archive.namelist():
                if not name.startswith('jittest/') or name.endswith('/') or name == 'jittest/_build_provenance.json':
                    continue
                if name in actual:
                    raise ValueError('duplicate wheel build input')
                actual[name] = hashlib.sha256(archive.read(name)).hexdigest()
    elif target == 'sdist':
        expected = recorded
        with tarfile.open(artifact) as archive:
            for member in archive.getmembers():
                name = '/'.join(Path(member.name).parts[1:])
                if not is_build_input(name):
                    continue
                if member.issym() or member.islnk():
                    raise ValueError('sdist build inputs cannot be symlinks')
                if member.isfile():
                    if name in actual:
                        raise ValueError('duplicate sdist build input')
                    stream = archive.extractfile(member)
                    if stream is None:
                        raise ValueError('missing sdist build input')
                    actual[name] = hashlib.sha256(stream.read()).hexdigest()
    else:
        raise ValueError('unsupported build target')
    if actual != expected:
        raise ValueError('finished artifact build inputs differ from captured identity')
