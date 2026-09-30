"""Install local/sdist Actions, or byte-reconcile remote archives to trusted Git.

GitHub's downloaded remote Action has no .git. Never invent its build SHA from
an ambient consumer checkout or silently install a newer mutable ref. Fetch only
the declared Action repository/ref and require all executable build inputs to
match the downloaded archive before installing that identified checkout.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD_PATHS = ('src', 'scripts', 'pyproject.toml', 'hatch_build.py', 'build_identity.py', 'action.yml')


def build_inputs(root: Path) -> dict[str, bytes]:
    inputs = {}
    for name in BUILD_PATHS:
        target = root / name
        if target.is_symlink():
            raise ValueError('Action build inputs cannot be symlinks')
        paths = target.rglob('*') if target.is_dir() else (target,)
        for path in paths:
            if path.is_symlink():
                raise ValueError('Action build inputs cannot be symlinks')
            if path.is_file():
                inputs[path.relative_to(root).as_posix()] = path.read_bytes()
    return inputs


def reconcile_archive(archive: Path, checkout: Path) -> None:
    if build_inputs(archive) != build_inputs(checkout):
        raise ValueError('downloaded Action build inputs differ from declared Git ref; refusing ref drift')


def build_env() -> dict[str, str]:
    # No ambient consumer-repository overrides, hooks or credentials in the
    # trusted public Action fetch/build. Keep ordinary OS/proxy prerequisites.
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
    return env


def fetch_action_source(repository: str, ref: str, destination: Path) -> None:
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise ValueError('remote Action requires an exact GitHub owner/repository')
    if (not re.fullmatch(r'[A-Za-z0-9_./-]+', ref) or ref.startswith('-')
            or '..' in ref or ref.endswith('/') or '//' in ref):
        raise ValueError('remote Action requires a valid explicit ref')
    def git(*args: str) -> None:
        subprocess.run(['git', '-C', str(destination), *args], check=True, timeout=120, env=build_env())
    git('init', '-q')
    git('config', 'core.autocrlf', 'false')
    git('remote', 'add', 'origin', f'https://github.com/{repository}.git')
    git('fetch', '--depth=1', '--no-tags', 'origin', ref)
    git('checkout', '-q', '--detach', 'FETCH_HEAD')


def install_action(source: Path, repository: str, ref: str, python: str) -> None:
    source = source.resolve()
    if (source / '.git').exists() or (source / 'src/jittest/_build_provenance.json').is_file():
        subprocess.run([python, '-m', 'pip', 'install', str(source)], check=True, timeout=300, env=build_env())
        return
    with tempfile.TemporaryDirectory(prefix='jittest-action-source-') as temp:
        checkout = Path(temp)
        fetch_action_source(repository, ref, checkout)
        reconcile_archive(source, checkout)
        subprocess.run([python, '-m', 'pip', 'install', str(checkout)], check=True, timeout=300, env=build_env())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--repository', default='')
    parser.add_argument('--ref', default='')
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    try:
        install_action(args.source, args.repository, args.ref, args.python)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'jittest Action install refused: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
