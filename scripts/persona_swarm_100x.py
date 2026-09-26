#!/usr/bin/env python3
"""100-persona human swarm + 100x concurrency torture for the jittest probe plane.

Deterministic (fixed seed), dependency-free, exports a JSON benchmark artefact:
P50/P95/P99 latency, throughput, RSS floor/ceiling, recovery latency, panics.

    PYTHONHASHSEED=0 python scripts/persona_swarm_100x.py --seed 20260919 \
        --workers 100 --burst 1000 --out docs/evidence/persona-swarm-20260919.json

Personas are synthetic human-inspired behaviours against HTTP probe endpoints
(impatient refreshers, curl HEAD users, POSTers, typo routes, garbage bytes,
slowloris, RST dropouts, oversized headers, HTTP/1.0, unicode paths) plus two
engineering personas that drive ``proc.run_bounded`` with malformed scripts and
hard timeouts. Conflicting-state writers register/unregister readiness checks
while readers hammer ``/readyz``.
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(_ROOT / 'src'))

from jittest import proc  # noqa: E402
from jittest.prod import probes, tracing  # noqa: E402

PERSONA_KINDS = (
    'impatient_refresh', 'curl_head', 'poster', 'typo_route', 'garbage_bytes',
    'rapid_cancel', 'slow_half_request', 'querystring_spam', 'oversized_header',
    'http10_client', 'unicode_path', 'network_dropout_rst', 'buildinfo_reader',
    'conflicting_writer', 'trace_burst', 'malformed_script', 'hard_timeout',
    'keepalive_pipeliner', 'options_prober', 'double_slash_route',
)
EXPECTED_STATUS = {
    'impatient_refresh': {200, 503}, 'curl_head': {200}, 'poster': {405},
    'typo_route': {404}, 'garbage_bytes': {400, None}, 'rapid_cancel': {None},
    'slow_half_request': {None, 400}, 'querystring_spam': {200},
    'oversized_header': {200, 400, 431, None}, 'http10_client': {200},
    'unicode_path': {404}, 'network_dropout_rst': {None, 200, 503},
    'buildinfo_reader': {200}, 'keepalive_pipeliner': {200}, 'options_prober': {405},
    'double_slash_route': {404, 200},
}


def _pct(sorted_ms: list[float], p: float) -> float:
    '''Nearest-rank percentile (deterministic; no interpolation surprises for small N).'''
    idx = min(len(sorted_ms) - 1, max(0, math.ceil(p / 100 * len(sorted_ms)) - 1))
    return round(sorted_ms[idx], 3)


def _rss_kib() -> int:
    try:
        with open('/proc/self/status', encoding='utf-8') as fh:
            for line in fh:
                if line.startswith('VmRSS:'):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def _raw(host: str, port: int, payload: bytes, *, read: bool = True,
         rst: bool = False, pause: float = 0.0) -> int | None:
    s = socket.create_connection((host, port), timeout=5.0)
    try:
        if rst:  # abortive close: kernel sends RST instead of FIN
            s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b'\x01\x00\x00\x00\x00\x00\x00\x00')
        if payload:
            s.sendall(payload)
        if pause:
            time.sleep(pause)  # persona pacing: a human pausing mid-request, not a test sleep
        if not read:
            return None
        head = s.recv(4096)
        if not head.startswith(b'HTTP/'):
            return None
        return int(head.split(b' ', 2)[1])
    except (TimeoutError, ConnectionError, OSError):
        return None
    finally:
        s.close()


def _get(host: str, port: int, path: str, method: str = 'GET', version: str = '1.1',
         extra: str = '') -> int | None:
    req = f'{method} {path} HTTP/{version}\r\nHost: x\r\n{extra}Connection: close\r\n\r\n'
    return _raw(host, port, req.encode('utf-8', 'surrogatepass'))


class Swarm:
    def __init__(self, seed: int, workers: int, burst: int) -> None:
        self.rng = random.Random(seed)
        self.seed, self.workers, self.burst = seed, workers, burst
        self.server = probes._ProbeServer(('127.0.0.1', 0), probes._Handler)
        self.host, self.port = self.server.server_address[:2]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.panics: list[str] = []
        self.unexpected: list[str] = []
        self.latencies_ms: list[float] = []
        self._lat_lock = threading.Lock()
        self._writer_lock = threading.Lock()

    # --- personas -------------------------------------------------------
    def persona(self, idx: int, kind: str) -> tuple[str, int | None]:
        h, p, rng = self.host, self.port, random.Random(self.seed * 1000 + idx)
        if kind == 'impatient_refresh':
            return kind, _get(h, p, '/readyz')
        if kind == 'curl_head':
            return kind, _get(h, p, '/healthz', method='HEAD')
        if kind == 'poster':
            return kind, _get(h, p, '/readyz', method='POST', extra='Content-Length: 2\r\n')
        if kind == 'options_prober':
            return kind, _get(h, p, '/healthz', method='OPTIONS')
        if kind == 'typo_route':
            return kind, _get(h, p, rng.choice(['/helthz', '/ready', '/health', '/']))
        if kind == 'double_slash_route':
            return kind, _get(h, p, '//healthz')
        if kind == 'garbage_bytes':
            return kind, _raw(h, p, bytes(rng.getrandbits(8) for _ in range(rng.randint(1, 512))))
        if kind == 'rapid_cancel':
            return kind, _raw(h, p, b'', read=False)
        if kind == 'slow_half_request':
            return kind, _raw(h, p, b'GET /readyz HTT', read=False, pause=0.02)
        if kind == 'querystring_spam':
            return kind, _get(h, p, '/healthz?' + 'x' * rng.randint(100, 4000))
        if kind == 'oversized_header':
            return kind, _get(h, p, '/healthz', extra='X-Pad: ' + 'A' * 16000 + '\r\n')
        if kind == 'http10_client':
            return kind, _get(h, p, '/healthz', version='1.0')
        if kind == 'unicode_path':
            return kind, _get(h, p, '/readyz/%C3%BC%C3%B1%C3%AF')
        if kind == 'network_dropout_rst':
            return kind, _raw(h, p, b'GET /readyz HTTP/1.1\r\nHost: x\r\n\r\n', read=False, rst=True)
        if kind == 'buildinfo_reader':
            return kind, _get(h, p, '/buildinfo')
        if kind == 'keepalive_pipeliner':
            req = b'GET /healthz HTTP/1.1\r\nHost: x\r\n\r\n' * 3
            return kind, _raw(h, p, req)
        if kind == 'conflicting_writer':
            name = f'swarm-check-{idx}'
            for _ in range(20):
                probes.register_readiness_check(name, lambda: None)
                _get(h, p, '/readyz')
                probes.unregister_readiness_check(name)
            return kind, 200
        if kind == 'trace_burst':
            tracer = tracing.get_tracer('swarm')
            for i in range(50):
                with tracer.span('outer', i=i), tracing.span('inner', persona=idx):
                    pass
            return kind, 200
        if kind == 'malformed_script':
            r = proc.run_bounded([sys.executable, '-c', 'def broken(:\n  pass'], timeout=20.0)
            return kind, 200 if r.returncode != 0 and 'SyntaxError' in r.stderr else 500
        if kind == 'hard_timeout':
            t0 = time.perf_counter()
            try:
                proc.run_bounded([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.3)
                return kind, 500
            except subprocess.TimeoutExpired as exc:
                t_wait_end = getattr(exc, 't_wait_end', t0 + 0.3)
                t_join_end = getattr(exc, 't_join_end', time.perf_counter())
                recover_ms = (t_join_end - t_wait_end) * 1000
                if not hasattr(exc, 't_wait_end'):
                    recover_ms = (time.perf_counter() - t0 - 0.3) * 1000
                return kind, 200 if recover_ms < 200 else 503
        raise ValueError(kind)

    def _run_persona(self, idx: int) -> None:
        kind = PERSONA_KINDS[idx % len(PERSONA_KINDS)]
        try:
            kind, status = self.persona(idx, kind)
        except Exception as exc:  # any persona exception is a panic surfaced by the server/engine
            self.unexpected.append(f'{kind}#{idx}: {type(exc).__name__}: {exc}')
            return
        expected = EXPECTED_STATUS.get(kind, {200})
        if status not in expected:
            self.unexpected.append(f'{kind}#{idx}: status {status} not in {sorted(map(str, expected))}')

    def _timed_get(self, _: int) -> None:
        t0 = time.perf_counter()
        status = _get(self.host, self.port, '/healthz')
        dt = (time.perf_counter() - t0) * 1000
        with self._lat_lock:
            self.latencies_ms.append(dt)
        if status != 200:
            self.unexpected.append(f'burst: status {status}')

    # --- orchestration --------------------------------------------------
    def run(self, personas: int = 120) -> dict:
        prev_hook = threading.excepthook
        threading.excepthook = lambda a: self.panics.append(f'{a.exc_type.__name__}: {a.exc_value}')
        gc.collect()
        tracemalloc.start()
        rss_floor = _rss_kib()
        baseline_checks = probes.readiness_checks()
        self.thread.start()
        rss_peak = rss_floor
        try:
            t0 = time.perf_counter()
            order = list(range(personas))
            self.rng.shuffle(order)  # out-of-order execution across persona kinds
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(self._run_persona, order))
            personas_s = time.perf_counter() - t0
            rss_peak = max(rss_peak, _rss_kib())

            t1 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                list(pool.map(self._timed_get, range(self.burst)))
            burst_s = time.perf_counter() - t1
            rss_peak = max(rss_peak, _rss_kib())

            # recovery: first clean request after chaos must answer within 200 ms
            t2 = time.perf_counter()
            rec_status = _get(self.host, self.port, '/readyz')
            recovery_ms = (time.perf_counter() - t2) * 1000
        finally:
            self.server.shutdown()
            self.server.server_close()
            threading.excepthook = prev_hook
        gc.collect()
        _, peak_traced = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        lat = sorted(self.latencies_ms) or [0.0]
        return {
            'seed': self.seed, 'workers': self.workers, 'personas': personas,
            'persona_kinds': len(PERSONA_KINDS), 'burst_requests': self.burst,
            'personas_elapsed_s': round(personas_s, 4), 'burst_elapsed_s': round(burst_s, 4),
            'throughput_rps': round(self.burst / burst_s, 1) if burst_s else None,
            'p50_ms': _pct(lat, 50), 'p95_ms': _pct(lat, 95), 'p99_ms': _pct(lat, 99),
            'max_ms': round(lat[-1], 3),
            'recovery_ms': round(recovery_ms, 3), 'recovery_status': rec_status,
            'rss_floor_mib': round(rss_floor / 1024, 1), 'rss_ceiling_mib': round(rss_peak / 1024, 1),
            'tracemalloc_peak_mib': round(peak_traced / 2**20, 2),
            'registry_drift': probes.readiness_checks() != baseline_checks,
            'server_thread_alive_after_shutdown': self.thread.is_alive(),
            'unhandled_panics': self.panics, 'unexpected': self.unexpected,
            'passed': not self.panics and not self.unexpected and recovery_ms < 200
            and rec_status in (200, 503) and probes.readiness_checks() == baseline_checks,
        }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--seed', type=int, default=20260919)
    ap.add_argument('--workers', type=int, default=100)
    ap.add_argument('--burst', type=int, default=1000)
    ap.add_argument('--personas', type=int, default=120)
    ap.add_argument('--out', type=Path, default=None)
    a = ap.parse_args(argv)
    if os.environ.get('PYTHONHASHSEED') != '0':
        print('warning: set PYTHONHASHSEED=0 for stable hashing; timing/RSS are not deterministic', file=sys.stderr)
    report = Swarm(a.seed, a.workers, a.burst).run(a.personas)
    text = json.dumps(report, sort_keys=True, indent=2)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
