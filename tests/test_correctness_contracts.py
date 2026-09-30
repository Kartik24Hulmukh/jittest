"""Offline council regressions: real git/runner/signatures, no private keys or APIs."""
import hashlib
import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

try:
    import pytest
except ImportError:
    raise unittest.SkipTest("correctness fixture suite requires pytest") from None

from jittest import action
from jittest.receipt import get_repo_canonical, sign_evidence, validate_schema, verify_receipt
from jittest.verify import VerifyRefusalError, verify_test


def platform_env():
    """Only OS/process necessities, never inherited API or signing credentials."""
    names = ('PATH', 'SystemRoot', 'SYSTEMROOT', 'COMSPEC', 'PATHEXT',
             'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'TEMP', 'TMP', 'HOME')
    return {name: os.environ[name] for name in names if name in os.environ}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def pair(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    git(repo, 'config', 'user.name', 'Fixture')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    (repo / 'app.py').write_text('def value():\n    return 1\n')
    test = repo / 'test_app.py'
    test.write_text('from app import value\ndef test_value():\n    assert value() == 1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-qb', 'pr')
    (repo / 'app.py').write_text('def value():\n    return 2\n')
    test.write_text(test.read_text(encoding="utf-8") + '# changed test\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'head')
    head = git(repo, 'rev-parse', 'HEAD')
    return repo, base, head, test


@pytest.fixture(autouse=True)
def public_test_seed():
    # Public deterministic test material only; never writes or reads a key file.
    with patch('jittest.receipt.get_or_create_signing_key', return_value=bytes(range(32))):
        yield


def produce(pair, tmp_path, **kwargs):
    repo, base, head, test = pair
    with patch('jittest.verify.provision_environment', return_value={'python_path': sys.executable}):
        return verify_test(repo, base, head, test, sandbox_mode='off',
                           output_path=tmp_path / 'receipt.json', **kwargs)


def test_assertion_receipt_is_independently_valid(pair, tmp_path):
    evidence, code = produce(pair, tmp_path)
    assert code == 0
    assert verify_receipt(evidence).valid
    assert [r['phase'] for r in evidence['verification_phases']] == ['base', 'head', 'head_rerun_2']


def test_nonassertion_head_is_not_a_behavioral_proof(pair, tmp_path):
    repo, _, _, _ = pair
    (repo / 'app.py').write_text('def value():\n    raise ValueError("regression")\n')
    git(repo, 'commit', '-qam', 'exception')
    pair = repo, pair[1], git(repo, 'rev-parse', 'HEAD'), pair[3]
    evidence, code = produce(pair, tmp_path)
    assert code != 0
    assert evidence['proven_catch'] is False
    assert verify_receipt(evidence).valid


@pytest.mark.parametrize('reruns', [-1, 0, 1])
def test_insufficient_reruns_refused_before_execution(pair, tmp_path, reruns):
    with pytest.raises(VerifyRefusalError, match='reruns'):
        produce(pair, tmp_path, reruns=reruns)


@pytest.mark.parametrize('version', ['1.0', '2.0', '2.1'])
@pytest.mark.parametrize('verdict', [[], {}, ['proven_catch']])
def test_signed_malformed_verdict_returns_invalid(version, verdict):
    receipt = sign_evidence({'schema_version': version, 'verdict': verdict})
    assert not validate_schema(receipt).valid
    assert not verify_receipt(receipt).valid


def test_single_record_cannot_claim_rerun_proof(pair, tmp_path):
    evidence, _ = produce(pair, tmp_path)
    evidence = deepcopy(evidence)
    evidence['verification_phases'] = evidence['verification_phases'][:2]
    evidence.pop('signature')
    assert not verify_receipt(sign_evidence(evidence)).valid


def noncatch_receipt(pair):
    repo, base, head, test = pair
    execution = {'outcome': 'PASS', 'failure_kind': 'none'}
    return sign_evidence({
        'schema_version': '2.1', 'tool': 'jittest verify', 'verdict': 'non_discriminating',
        'disposition': 'head_passed', 'proven_catch': False, 'rerun_agreement': True,
        'wall_clock_s': 0.0, 'sandbox': {'mode': 'off', 'backend': 'none'},
        'base_execution': execution, 'head_execution': execution,
        'provenance': {'repo_path': str(repo), 'repo_canonical': get_repo_canonical(repo), 'base_sha': base, 'head_sha': head,
                       'test_file_name': test.name, 'test_file_sha256': hashlib.sha256(test.read_bytes()).hexdigest(),
                       'tool_commit_sha': 'a' * 40, 'rel_path': '.'},
    })


def run_consumer(pair, tmp_path, env=None, policy='block-on-refusal', pr=None):
    repo = pair[0]
    environ = {**platform_env(), 'GITHUB_EVENT_NAME': 'push', 'JITTEST_BASE': pair[1], 'JITTEST_HEAD': pair[2]}
    environ.update(env or {})
    with patch.dict(os.environ, environ, clear=True), \
         patch('jittest.action.upsert_pr_comment', return_value='local') as comment, \
         patch('jittest.action.verify_test', return_value=(noncatch_receipt(pair), 1)) as verifier:
        code = action.run_action(repo, pr_number=pr, policy=policy, sandbox_override='off', output_dir=tmp_path / 'out')
    return code, comment, verifier


def test_blank_pr_number_infers_event_pair_not_merge(pair, tmp_path):
    repo, base, head, _ = pair
    git(repo, 'checkout', '-q', 'main')
    git(repo, 'merge', '--no-ff', '-qm', 'merge checkout', 'pr')
    assert git(repo, 'rev-parse', 'HEAD') != head
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'number': 42, 'pull_request': {'number': 42, 'base': {'sha': base, 'repo': {'full_name': 'owner/repo'}}, 'head': {'sha': head, 'repo': {'full_name': 'owner/repo'}}}}))
    code, comment, verifier = run_consumer(pair, tmp_path, {'JITTEST_BASE': '', 'JITTEST_HEAD': '', 'JITTEST_PR_NUMBER': '', 'GITHUB_REF': 'refs/pull/42/merge', 'GITHUB_EVENT_NAME': 'pull_request', 'GITHUB_EVENT_PATH': str(event)}, pr='')
    assert code == 0
    assert verifier.call_args.kwargs['head_ref'] == head
    assert verifier.call_args.kwargs['base_ref'] == base
    assert comment.call_args.kwargs['pr_number'] == '42'


@pytest.mark.parametrize('policy, expected', [('advisory', 0), ('strict', 1), ('block-on-refusal', 1)])
def test_missing_pair_object_is_visible_refusal(pair, tmp_path, policy, expected):
    code, comment, verifier = run_consumer(pair, tmp_path, {'JITTEST_BASE': 'missing-ref'}, policy)
    assert code == expected
    assert not verifier.called
    assert 'REFUSED' in comment.call_args.args[0]
    assert 'Zero test files' not in comment.call_args.args[0]


def test_unresolved_pr_cannot_fall_back_to_checkout(pair, tmp_path):
    with patch('jittest.action.fetch_pr_base_head', side_effect=RuntimeError('offline')):
        code, comment, verifier = run_consumer(pair, tmp_path, {'JITTEST_BASE': '', 'JITTEST_HEAD': '', 'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'pull_request'}, pr=42)
    assert code == 1
    assert not verifier.called
    assert 'REFUSED' in comment.call_args.args[0]


def test_api_resolver_uses_repository_identity(pair, tmp_path):
    with patch('jittest.action.fetch_pr_base_head', return_value=pair[1:3]) as resolver:
        run_consumer(pair, tmp_path, {'JITTEST_BASE': '', 'JITTEST_HEAD': '', 'GITHUB_REPOSITORY': 'owner/repo'}, pr=42)
    assert resolver.call_args.args[0] == 'owner/repo'


def test_diff_failure_does_not_become_empty_diff(pair, tmp_path):
    with patch('jittest.action.get_changed_files', side_effect=subprocess.CalledProcessError(128, ['git', 'diff'])):
        code, comment, verifier = run_consumer(pair, tmp_path)
    assert code == 1
    assert not verifier.called
    assert 'REFUSED' in comment.call_args.args[0]


@pytest.mark.parametrize('entrypoint', ['jittest.action', 'jittest.cli'])
def test_real_entrypoint_blank_composite_pr_env_uses_event_pair(pair, tmp_path, entrypoint):
    repo, base, head, _ = pair
    git(repo, 'checkout', '-q', 'main')
    git(repo, 'merge', '--no-ff', '-qm', 'synthetic PR merge', 'pr')
    merge = git(repo, 'rev-parse', 'HEAD')
    assert merge != head
    event = tmp_path / 'event.json'
    event.write_text(json.dumps({'number': 42, 'pull_request': {
        'number': 42, 'base': {'sha': base, 'repo': {'full_name': 'owner/repo'}},
        'head': {'sha': head, 'repo': {'full_name': 'owner/repo'}},
    }}))
    # Only API/comment, provisioning and private-key boundaries are replaced.
    # CLI parsing, Action main(), git diff, worktrees, mini runner, signing,
    # independent receipt verification and policy conclusion are real.
    bootstrap = tmp_path / 'bootstrap'
    bootstrap.mkdir()
    (bootstrap / 'sitecustomize.py').write_text('''import os, sys
from pathlib import Path
import jittest.action, jittest.verify, jittest.receipt, jittest.github
jittest.verify.provision_environment = lambda *a, **kw: {"python_path": sys.executable}
jittest.receipt.get_or_create_signing_key = lambda *a, **kw: bytes(range(32))
def comment(body, **kw):
    Path(os.environ["FIXTURE_COMMENT"]).write_text(body + "\\nPR=" + str(kw.get("pr_number")), encoding="utf-8")
    return "local fixture"
jittest.action.upsert_pr_comment = comment
jittest.github.upsert_pr_comment = comment
''')
    source = os.getenv('JITTEST_CONTRACT_SOURCE_ROOT') or str(Path(__file__).resolve().parents[1] / 'src')
    env = {**platform_env(), 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PYTHONPATH': str(bootstrap) + os.pathsep + source,
           'JITTEST_FORCE_MINIRUNNER': '1', 'JITTEST_REPO_PATH': str(repo),
           'JITTEST_PR_NUMBER': '', 'GITHUB_REF': 'refs/pull/42/merge',
           'GITHUB_REPOSITORY': 'owner/repo', 'GITHUB_EVENT_NAME': 'pull_request',
           'GITHUB_EVENT_PATH': str(event), 'JITTEST_SANDBOX_MODE': 'off',
           'JITTEST_POLICY': 'strict', 'JITTEST_OUTPUT_DIR': str(tmp_path / 'out'),
           'FIXTURE_COMMENT': str(tmp_path / 'comment.txt')}
    cmd = [sys.executable, '-m', entrypoint]
    if entrypoint == 'jittest.cli':
        cmd += ['action', '--repo', str(repo), '--sandbox', 'off']
    result = subprocess.run(cmd, env=env, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    output = tmp_path / ('jittest-evidence' if entrypoint == 'jittest.cli' else 'out')
    receipts = list(output.glob('evidence-*.json'))
    assert len(receipts) == 1, result.stdout + result.stderr
    evidence = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert evidence['provenance']['base_sha'] == base
    assert evidence['provenance']['head_sha'] == head
    assert evidence['provenance']['head_sha'] != merge
    assert evidence['verdict'] == 'proven_catch'
    assert verify_receipt(evidence, expected_base=base, expected_head=head).valid
    assert 'PR=42' in (tmp_path / 'comment.txt').read_text(encoding="utf-8")


@pytest.mark.parametrize('alter', ['absent', 'duplicate', 'wrong_revision', 'wrong_test', 'different_failure'])
def test_rerun_records_must_prove_same_assertion(pair, tmp_path, alter):
    evidence, _ = produce(pair, tmp_path)
    if alter == 'absent':
        del evidence['verification_phases']
    elif alter == 'duplicate':
        evidence['verification_phases'][-1]['phase'] = 'head'
    elif alter == 'wrong_revision':
        evidence['verification_phases'][-1]['revision'] = pair[1]
    elif alter == 'wrong_test':
        evidence['verification_phases'][-1]['test_sha256'] = 'f' * 64
    else:
        evidence['verification_phases'][-1]['failure_kind'] = 'error'
    evidence.pop('signature')
    assert not verify_receipt(sign_evidence(evidence)).valid


@pytest.mark.parametrize('reruns', [2, 3])
def test_requested_execution_count_is_honored(pair, tmp_path, reruns):
    evidence, code = produce(pair, tmp_path, reruns=reruns)
    assert code == 0
    assert len(evidence['verification_phases']) == 1 + reruns
    assert verify_receipt(evidence).valid


def test_fail_outcome_with_different_failure_kind_is_not_agreement(pair, tmp_path):
    from types import SimpleNamespace

    from jittest.execute import FailureKind, Outcome
    runs = [SimpleNamespace(outcome=o, failure_kind=f, returncode=rc, stdout='', stderr='')
            for o, f, rc in [(Outcome.PASS, FailureKind.NONE, 0),
                             (Outcome.FAIL, FailureKind.ASSERTION, 1),
                             (Outcome.FAIL, FailureKind.ERROR, 1)]]
    with patch('jittest.verify.run_test', side_effect=runs):
        evidence, code = produce(pair, tmp_path)
    assert code != 0
    assert evidence['rerun_agreement'] is False
    assert not evidence['proven_catch']
    assert verify_receipt(evidence).valid


@pytest.mark.parametrize('policy, expected', [('advisory', 0), ('strict', 1), ('block-on-refusal', 1)])
def test_consumer_rejects_invalid_signed_producer_receipt(pair, tmp_path, policy, expected):
    evidence, _ = produce(pair, tmp_path)
    evidence['head_execution']['failure_kind'] = 'error'
    evidence.pop('signature')
    invalid = sign_evidence(evidence)
    repo = pair[0]
    with patch.dict(os.environ, {**platform_env(), 'GITHUB_EVENT_NAME': 'push', 'JITTEST_BASE': pair[1], 'JITTEST_HEAD': pair[2]}, clear=True), \
         patch('jittest.action.upsert_pr_comment', return_value='local') as comment, \
         patch('jittest.action.verify_test', return_value=(invalid, 0)):
        code = action.run_action(repo, policy=policy, sandbox_override='off', output_dir=tmp_path / 'out')
    assert code == expected
    assert 'refused_invalid_receipt' in comment.call_args.args[0]
    assert '**Proven Catches**: 0' in comment.call_args.args[0]


@pytest.mark.parametrize('field', ['verdict', 'provenance', 'sandbox', 'base_execution', 'head_execution', 'rerun_agreement', 'verification_phases'])
@pytest.mark.parametrize('shape', [[], {}, 1, None])
def test_signed_malformed_shapes_never_raise(pair, field, shape):
    evidence = noncatch_receipt(pair)
    evidence[field] = shape
    evidence.pop('signature')
    signed = sign_evidence(evidence)
    result = verify_receipt(signed, expected_base=pair[1], expected_head=pair[2], expected_repo=str(pair[0]))
    # Extra optional phases may have no bearing on non-catch receipts.
    if field != 'verification_phases':
        assert not result.valid


@pytest.mark.parametrize('data', [[], {}, {'source_sha': 'x' * 40, 'working_diff_sha256': 'a' * 64},
                                 {'source_sha': 'a' * 40, 'working_diff_sha256': None}])
def test_malformed_installed_build_identity_refuses(tmp_path, data):
    from jittest.verify import _jittest_version_and_sha
    (tmp_path / '_build_provenance.json').write_text(json.dumps(data))
    with patch('jittest.verify.resources.files', return_value=tmp_path), \
         pytest.raises(VerifyRefusalError, match='build provenance is invalid'):
        _jittest_version_and_sha()


def test_installed_identity_resource_precedes_repository_lookup(tmp_path):
    from jittest.verify import _jittest_version_and_sha
    (tmp_path / '_build_provenance.json').write_text(json.dumps({'source_sha': 'b' * 40, 'working_diff_sha256': 'c' * 64}))
    with patch('jittest.verify.resources.files', return_value=tmp_path), \
         patch('jittest.verify.subprocess.check_output', side_effect=AssertionError('must not inspect installed cwd')):
        _, sha = _jittest_version_and_sha()
    assert sha == 'b' * 40


def test_installed_missing_identity_cannot_borrow_checkout_sha(tmp_path):
    from jittest.verify import _jittest_version_and_sha
    with patch('jittest.verify.resources.files', return_value=tmp_path), \
         patch('jittest.verify.__file__', str(tmp_path / 'site-packages' / 'jittest' / 'verify.py')), \
         pytest.raises(VerifyRefusalError, match='tool source identity unavailable'):
        _jittest_version_and_sha()


def test_installed_wheel_producer_and_consumer_contract(pair, tmp_path):
    wheel = os.getenv('JITTEST_TEST_WHEEL')
    if not wheel:
        pytest.skip('set JITTEST_TEST_WHEEL to a freshly built wheel for offline installed-artifact acceptance')
    target = tmp_path / 'installed'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--target', str(target), wheel], check=True, capture_output=True, text=True, timeout=60)
    with patch.dict(os.environ, {'JITTEST_CONTRACT_SOURCE_ROOT': str(target)}):
        test_real_entrypoint_blank_composite_pr_env_uses_event_pair(pair, tmp_path, 'jittest.cli')


@pytest.mark.parametrize('scenario', ['empty_diff', 'diff_failed', 'invalid_receipt', 'sandbox_refused'])
def test_step_summary_survives_denied_comments(pair, tmp_path, scenario):
    summary = tmp_path / 'summary.md'
    env = {**platform_env(), 'GITHUB_EVENT_NAME': 'push', 'JITTEST_BASE': pair[1], 'JITTEST_HEAD': pair[2],
           'GITHUB_STEP_SUMMARY': str(summary)}
    from contextlib import ExitStack

    from jittest.sandbox import SandboxPlan
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env, clear=True))
        stack.enter_context(patch('jittest.action.upsert_pr_comment', side_effect=RuntimeError('comment denied')))
        if scenario == 'empty_diff':
            stack.enter_context(patch('jittest.action.get_changed_files', return_value=[]))
        elif scenario == 'diff_failed':
            stack.enter_context(patch('jittest.action.get_changed_files', side_effect=subprocess.CalledProcessError(128, ['git', 'diff'])))
        elif scenario == 'invalid_receipt':
            stack.enter_context(patch('jittest.action.verify_test', return_value=({'verdict': 'proven_catch', 'proven_catch': True}, 0)))
        else:
            stack.enter_context(patch('jittest.action.get_trust_context', return_value='fork'))
            stack.enter_context(patch('jittest.action.plan_sandbox', return_value=SandboxPlan(backend='none', mode='required')))
        code = action.run_action(pair[0], policy='strict', sandbox_override='off', output_dir=tmp_path / 'out')
    assert code == (0 if scenario == 'empty_diff' else 1)
    text = summary.read_text(encoding="utf-8")
    assert 'jittest' in text
    assert len(text) <= 65537
    if scenario != 'empty_diff':
        assert 'refus' in text.lower()


def test_required_no_backend_cli_emits_signed_nonproof_refusal(pair, tmp_path):
    repo, base, head, test = pair
    bootstrap = tmp_path / 'bootstrap'
    bootstrap.mkdir()
    (bootstrap / 'sitecustomize.py').write_text('''import jittest.verify, jittest.receipt
from jittest.sandbox import SandboxUnavailable
jittest.receipt.get_or_create_signing_key = lambda *a, **kw: bytes(range(32))
def unavailable(*a, **kw):
    raise SandboxUnavailable("fixture: no available backend")
jittest.verify.plan_sandbox = unavailable
''')
    source = str(Path(__file__).resolve().parents[1] / 'src')
    env = {**platform_env(), 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path), 'PYTHONPATH': str(bootstrap) + os.pathsep + source}
    output = tmp_path / 'refusal.json'
    result = subprocess.run([sys.executable, '-m', 'jittest.cli', 'verify', '--repo', str(repo),
                             '--base', base, '--head', head, '--test', str(test),
                             '--sandbox-mode', 'required', '--output', str(output), '--json'],
                            cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 2
    evidence = json.loads(output.read_text(encoding="utf-8"))
    assert evidence['verdict'] == 'inconclusive'
    assert evidence['proven_catch'] is False
    assert evidence['refusal']['code'] == 'sandbox_unavailable'
    assert evidence['base_execution']['outcome'] == 'NOTRUN'
    assert evidence['head_execution']['outcome'] == 'NOTRUN'
    assert verify_receipt(evidence, expected_base=base, expected_head=head).valid


def test_no_backend_refusal_cannot_claim_executed_candidate(pair, tmp_path):
    from jittest.sandbox import SandboxPlan
    from jittest.verify import make_refusal_receipt
    evidence = make_refusal_receipt(pair[0], pair[1], pair[2], pair[3],
                                    sbx_plan=SandboxPlan(backend='none', mode='required'))
    assert verify_receipt(evidence).valid
    evidence.pop('signature')
    evidence['verification_phases'] = [{'phase': 'head', 'outcome': 'FAIL'}]
    assert not verify_receipt(sign_evidence(evidence)).valid


def test_body_import_error_is_not_behavioral_and_receipt_remains_valid(pair, tmp_path):
    repo = pair[0]
    (repo / 'app.py').write_text('def value():\n    import jittest_fixture_missing_dependency\n')
    git(repo, 'commit', '-qam', 'runtime import error')
    broken = (repo, pair[1], git(repo, 'rev-parse', 'HEAD'), pair[3])
    evidence, code = produce(broken, tmp_path)
    assert code != 0
    assert evidence['proven_catch'] is False
    assert verify_receipt(evidence).valid


def test_crlf_receipt_binds_original_and_executed_bytes(pair, tmp_path):
    repo, base, head, test = pair
    test.write_bytes(test.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    git(repo, 'config', 'core.autocrlf', 'false')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'exact CRLF candidate')
    head = git(repo, 'rev-parse', 'HEAD')
    evidence, code = produce((repo, base, head, test), tmp_path)
    expected = hashlib.sha256(test.read_bytes()).hexdigest()
    assert code == 0
    assert evidence['provenance']['test_file_sha256'] == expected
    assert all(phase['test_sha256'] == expected for phase in evidence['verification_phases'])
    assert verify_receipt(evidence, strict_signer=True,
                          expected_signer='03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8',
                          expected_base=base, expected_head=head,
                          expected_test_sha256=expected, expected_repo=get_repo_canonical(repo)).valid


def test_non_utf8_candidate_is_explicit_refusal(pair, tmp_path):
    pair[3].write_bytes(b'# invalid UTF-8\xff\n')
    with pytest.raises(VerifyRefusalError, match='not UTF-8'):
        produce(pair, tmp_path)


def test_refusal_receipt_binds_raw_candidate_bytes(pair, tmp_path):
    from jittest.verify import make_refusal_receipt
    test = pair[3]
    test.write_bytes(b'# CRLF refusal candidate\r\n')
    receipt = make_refusal_receipt(pair[0], pair[1], pair[2], test)
    assert receipt['provenance']['test_file_sha256'] == hashlib.sha256(test.read_bytes()).hexdigest()
