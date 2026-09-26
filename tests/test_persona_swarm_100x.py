"""100-persona human swarm + 100x concurrency torture (deterministic, CI-sized).

The full-size run (100 workers, 1000-request burst, 120 personas) is
``scripts/persona_swarm_100x.py``; its frozen artefact lives in
``docs/evidence/persona-swarm-20260919.json``. This module runs the same engine
at a size that finishes in a few seconds on a CI runner and pins the invariants:
zero unhandled panics, every persona gets its contract status, the readiness
registry shows no drift after conflicting writers, and the first clean request
after chaos answers in under 200 ms.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from jittest import proc
from jittest.prod.wsgi import ProbeApp

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / 'scripts' / 'persona_swarm_100x.py'
_ARTEFACT = _ROOT / 'docs' / 'evidence' / 'persona-swarm-20260919.json'


def _load_swarm():
    spec = importlib.util.spec_from_file_location('persona_swarm_100x', _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class PersonaSwarmTests(unittest.TestCase):
    def test_100_personas_at_100x_zero_panics_and_sub_200ms_recovery(self):
        swarm_mod = _load_swarm()
        assert len(swarm_mod.PERSONA_KINDS) >= 20
        report = swarm_mod.Swarm(seed=20260919, workers=100, burst=300).run(personas=100)
        assert report['unhandled_panics'] == [], report['unhandled_panics']
        assert report['unexpected'] == [], report['unexpected'][:10]
        assert report['recovery_status'] in (200, 503)
        assert report['recovery_ms'] < 200, report['recovery_ms']
        assert report['registry_drift'] is False
        assert report['server_thread_alive_after_shutdown'] is False
        assert report['p99_ms'] < 2000  # generous CI bound; the launch artefact records the real number
        assert report['tracemalloc_peak_mib'] < 64
        assert report['passed'] is True


    def test_swarm_report_is_deterministic_for_a_fixed_seed(self):
        swarm_mod = _load_swarm()
        a = swarm_mod.Swarm(seed=7, workers=8, burst=40).run(personas=20)
        b = swarm_mod.Swarm(seed=7, workers=8, burst=40).run(personas=20)
        stable = ('seed', 'workers', 'personas', 'persona_kinds', 'burst_requests',
                  'unhandled_panics', 'unexpected', 'registry_drift', 'passed')
        assert {k: a[k] for k in stable} == {k: b[k] for k in stable}
        assert a['passed'] and b['passed']


    def test_frozen_launch_artefact_passed(self):
        data = json.loads(_ARTEFACT.read_text(encoding='utf-8'))
        assert data['passed'] is True
        assert data['workers'] == 100 and data['personas'] >= 100 and data['burst_requests'] >= 1000
        assert data['unhandled_panics'] == [] and data['unexpected'] == []
        assert data['recovery_ms'] < 200
        for key in ('p50_ms', 'p95_ms', 'p99_ms', 'throughput_rps', 'rss_floor_mib', 'rss_ceiling_mib'):
            assert isinstance(data[key], (int, float)) and data[key] > 0, key


    def test_run_bounded_has_no_polling_sleep(self):
        """perf(proc): the 20 ms poll/sleep loop was replaced by native Popen.wait."""
        src = (_ROOT / 'src' / 'jittest' / 'proc.py').read_text(encoding='utf-8')
        assert 'time.sleep' not in src
        assert 'proc.wait(timeout=timeout)' in src


    def test_run_bounded_timeout_recovers_within_200ms(self):
        t0 = time.perf_counter()
        with self.assertRaises(subprocess.TimeoutExpired) as ctx:
            proc.run_bounded([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.25)
        exc = ctx.exception
        t_wait_end = getattr(exc, 't_wait_end', t0 + 0.25)
        t_join_end = getattr(exc, 't_join_end', time.perf_counter())
        cleanup_ms = (t_join_end - t_wait_end) * 1000
        assert cleanup_ms < 200, cleanup_ms


    def test_run_bounded_malformed_script_is_a_result_not_a_panic(self):
        result = proc.run_bounded([sys.executable, '-c', 'def broken(:\n  pass'], timeout=20.0)
        assert result.returncode != 0
        assert 'SyntaxError' in result.stderr


# --- erratic payload shapes against the WSGI probe app (fixed-seed property) ---
try:
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
except ImportError:  # pragma: no cover - hypothesis is a soft dev dependency
    HealthCheck = given = settings = st = None

# Class decorators run before unittest can apply a skip. Do not evaluate
# Hypothesis strategies or decorators in the dependency-free CI lane.
if st is not None:
    _erratic_text = st.text(min_size=0, max_size=64)

    class ProbeAppPropertyTests(unittest.TestCase):
        @settings(max_examples=200, derandomize=True, deadline=None,
                  suppress_health_check=[HealthCheck.too_slow])
        @given(path=st.one_of(_erratic_text, st.sampled_from(['/healthz', '/readyz', '/HEALTHZ', '/healthz/', ''])),
               method=st.one_of(_erratic_text, st.sampled_from(['GET', 'HEAD', 'POST', 'BREW', ''])),
               ready=st.booleans(), drain=st.booleans())
        def test_probe_app_never_raises_and_always_answers_json(self, path, method, ready, drain):
            app = ProbeApp()
            app.set_ready(ready)
            if drain:
                app.drain()
            captured: dict = {}

            def start_response(status, headers):
                captured['status'] = status
                captured['headers'] = dict(headers)

            body = b''.join(app({'PATH_INFO': path, 'REQUEST_METHOD': method}, start_response))
            status = int(captured['status'][:3])
            assert status in (200, 404, 405, 503)
            assert captured['headers']['Content-Type'] == 'application/json'
            declared = int(captured['headers']['Content-Length'])
            if method == 'HEAD':  # RFC 9110 9.3.2: same headers as GET, no body
                assert body == b'' and declared > 0
                payload = None
            else:
                assert declared == len(body)
                payload = json.loads(body)
            if path not in ('/healthz', '/readyz'):
                assert status == 404
            elif method not in ('GET', 'HEAD'):
                assert status == 405 and captured['headers']['Allow'] == 'GET, HEAD'
            elif path == '/healthz':
                assert status == 200 and payload in (None, {'status': 'alive'})
            else:
                expect_ready = ready and not drain
                assert (status == 200) is expect_ready
                assert payload is None or payload['status'] == ('ready' if expect_ready else 'not_ready')
