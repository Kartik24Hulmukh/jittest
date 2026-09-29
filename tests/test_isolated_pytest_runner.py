"""Pinned images must use their real pytest without probing candidate code on host."""
from unittest.mock import patch

from jittest import execute as E
from jittest.sandbox import SandboxPlan

PIN = 'localhost:5000/jittest@sha256:' + 'a' * 64


def test_pytest_probe_is_container_wrapped(tmp_path):
    sbx = SandboxPlan(backend='docker', runtime_image=PIN, image=PIN)
    with patch.object(E, '_run_process', return_value=(0, 'pytest 8.3.4', '')) as proc:
        runner = E.detect_isolated_runner(tmp_path, sbx, timeout_s=5)
    argv = proc.call_args.args[0]
    assert argv[:2] == ['docker', 'run']
    assert argv[argv.index('--network') + 1] == 'none'
    assert '-I' in argv
    assert 'pytest' in runner


def test_stock_image_does_not_pretend_to_have_pytest(tmp_path):
    sbx = SandboxPlan(backend='docker')
    with patch.object(E, '_run_process') as proc:
        runner = E.detect_isolated_runner(tmp_path, sbx, timeout_s=5)
    proc.assert_not_called()
    assert 'jittest._minirunner' in runner


def test_missing_image_pytest_falls_back_honestly(tmp_path):
    sbx = SandboxPlan(backend='docker', runtime_image=PIN, image=PIN)
    with patch.object(E, '_run_process', return_value=(1, '', 'no pytest')):
        runner = E.detect_isolated_runner(tmp_path, sbx, timeout_s=5)
    assert 'jittest._minirunner' in runner
