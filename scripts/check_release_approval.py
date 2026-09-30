"""Bind exact release bytes and effects to an externally approved raw JSON digest.

Offline only. This verifies effective inputs, not the hosted origin of vars.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import tomllib
from pathlib import Path

EMPTY_SHA256 = hashlib.sha256(b'').hexdigest()
APPROVAL_NAME = 'release-approval.json'
EFFECTS = ('pypi', 'github_release', 'floating_v0')


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    def constant(_value):
        raise ValueError('nonfinite JSON number')

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('nonfinite JSON number')
        return parsed

    value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                       parse_constant=constant, parse_float=number)
    if not isinstance(value, dict):
        raise ValueError('JSON document must be an object')
    return value


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def require_hex(value, length):
    if not isinstance(value, str) or not re.fullmatch(rf'[0-9a-f]{{{length}}}', value):
        raise ValueError('invalid digest or source identity')
    return value


def git(root: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
    return subprocess.check_output(['git', '-C', str(root), *args], env=env,
                                   stderr=subprocess.PIPE, timeout=30).decode().strip()


def context(root: Path, build_attempt: str) -> dict:
    names = ('GITHUB_REPOSITORY', 'GITHUB_SHA', 'GITHUB_REF', 'GITHUB_EVENT_NAME',
             'GITHUB_RUN_ID', 'GITHUB_WORKFLOW_REF')
    values = {name: os.environ.get(name, '') for name in names}
    if not all(values.values()):
        raise ValueError('missing release execution context')
    if values['GITHUB_EVENT_NAME'] not in ('push', 'workflow_dispatch'):
        raise ValueError('unsupported release event')
    if not re.fullmatch(r'[1-9][0-9]*', values['GITHUB_RUN_ID']):
        raise ValueError('invalid run identity')
    if not re.fullmatch(r'[1-9][0-9]*', build_attempt):
        raise ValueError('missing or invalid original build attempt')
    source = require_hex(values['GITHUB_SHA'], 40)
    if git(root, 'rev-parse', 'HEAD') != source:
        raise ValueError('checkout differs from release source')
    version = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
    ref = values['GITHUB_REF']
    if ref.startswith('refs/tags/'):
        if ref != f'refs/tags/v{version}':
            raise ValueError('tag/version mismatch')
        if git(root, 'rev-parse', f'{ref}^{{commit}}') != source:
            raise ValueError('tag/source mismatch')
    elif values['GITHUB_EVENT_NAME'] == 'push':
        raise ValueError('publication requires a tag push')
    publish = values['GITHUB_EVENT_NAME'] == 'push' and ref.startswith('refs/tags/v')
    stable = re.fullmatch(r'refs/tags/v0\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)', ref) is not None
    return {'repository': values['GITHUB_REPOSITORY'], 'source_sha': source,
            'source_tree': require_hex(git(root, 'rev-parse', 'HEAD^{tree}'), 40),
            'ref': ref, 'version': version, 'event': values['GITHUB_EVENT_NAME'],
            'run_id': values['GITHUB_RUN_ID'], 'build_attempt': build_attempt,
            'workflow_ref': values['GITHUB_WORKFLOW_REF'],
            'effects': {'pypi': publish, 'github_release': publish,
                        'floating_v0': publish and stable}}


def artifact_manifest(dist: Path) -> tuple[str, dict, dict]:
    raw = (dist / 'candidate-manifest.json').read_bytes()
    candidate = strict_json(raw)
    artifacts = candidate.get('artifacts')
    if not isinstance(artifacts, dict) or len(artifacts) != 2:
        raise ValueError('exact wheel and sdist manifest required')
    names = set(artifacts)
    if any(not isinstance(n, str) or Path(n).name != n or '/' in n or '\\' in n for n in names):
        raise ValueError('artifact filename must be a basename')
    if sum(n.endswith('.whl') for n in names) != 1 or sum(n.endswith('.tar.gz') for n in names) != 1:
        raise ValueError('exact wheel and sdist required')
    on_disk = {p.name for pattern in ('*.whl', '*.tar.gz') for p in dist.glob(pattern)}
    if on_disk != names:
        raise ValueError('downloaded distribution inventory differs from manifest')
    for name, expected in artifacts.items():
        require_hex(expected, 64)
        if (dist / name).is_symlink() or sha256((dist / name).read_bytes()) != expected:
            raise ValueError('downloaded artifact bytes differ from manifest')
    return sha256(raw), candidate, artifacts


def expected_manifest(dist: Path, root: Path, build_attempt: str) -> dict:
    execution = context(root, build_attempt)
    digest, candidate, artifacts = artifact_manifest(dist)
    if candidate.get('version') != execution['version'] or candidate.get('source_sha') != execution['source_sha']:
        raise ValueError('candidate version/source mismatch')
    if candidate.get('working_diff_sha256') != EMPTY_SHA256:
        raise ValueError('release candidate must use clean source')
    return {'schema': 'jittest-release-approval-v1', **execution,
            'candidate_manifest_sha256': digest, 'artifacts': artifacts}


def create(dist: Path, root: Path, build_attempt: str) -> str:
    manifest = expected_manifest(dist, root, build_attempt)
    raw = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    (dist / APPROVAL_NAME).write_bytes(raw)
    return sha256(raw)


def verify(dist: Path, root: Path, build_attempt: str, approved_digest: str, effect: str) -> str:
    require_hex(approved_digest, 64)
    raw = (dist / APPROVAL_NAME).read_bytes()
    if sha256(raw) != approved_digest:
        raise ValueError('raw release manifest differs from external approval')
    approved = strict_json(raw)
    expected = expected_manifest(dist, root, build_attempt)
    # Dict equality treats 1 == True: require actual booleans independently.
    if (not isinstance(approved.get('effects'), dict)
            or set(approved['effects']) != set(EFFECTS)
            or any(type(approved['effects'].get(key)) is not bool for key in EFFECTS)):
        raise ValueError('effect flags must be explicit booleans')
    if any(approved['effects'][key] and not expected['effects'][key] for key in EFFECTS):
        raise ValueError('approval cannot enable an effect forbidden by event or release channel')
    # Reviewers may deliberately approve a narrower subset of the requested effects.
    expected['effects'] = approved['effects']
    if approved != expected:
        raise ValueError('approved manifest differs from release context or exact bytes')
    if effect not in EFFECTS or approved['effects'][effect] is not True:
        raise ValueError('requested release effect is not approved')
    return sha256(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--create', action='store_true')
    parser.add_argument('--effect', choices=EFFECTS)
    parser.add_argument('--build-attempt', required=True)
    args = parser.parse_args()
    if args.create and args.effect or not args.create and not args.effect:
        parser.error('choose --create or --effect')
    try:
        digest = (create(args.dist, args.root, args.build_attempt) if args.create else
                  verify(args.dist, args.root, args.build_attempt,
                         os.environ.get('JITTEST_RELEASE_APPROVAL_SHA256', ''), args.effect))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError):
        # Do not echo payloads, environment values or credentials into logs.
        parser.exit(1, 'release approval refused: missing, invalid or mismatched approval/context/bytes\n')
    print(f'release approval {"candidate" if args.create else "verified"}: sha256={digest}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
