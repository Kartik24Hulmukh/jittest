"""Production-surface tests: probes, structured logs, tracing, fixed-seed bench.

These are real assertions on real behaviour under concurrency -- not smoke
tests. Every test here is designed to fail loudly if the production surface
regresses determinism, leaks unstructured output, or panics under load.
"""

import io
import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from jittest.prod import bench, probes, tracing
from jittest.prod import logging as jlog


class ProbeContractTests(unittest.TestCase):
    def test_healthz_is_cheap_and_ok(self):
        result = probes.healthz()
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.http_status, 200)

    def test_readyz_reports_every_builtin_check(self):
        result = probes.readyz()
        self.assertEqual(result.status, "ready", result.to_dict())
        for name in ("core_imports", "receipt_schema", "writable_tmp"):
            self.assertEqual(result.checks[name], "ok")

    def test_readyz_fails_closed_on_broken_dependency(self):
        def exploding():
            raise RuntimeError("dependency down")

        probes.register_readiness_check("chaos_injected", exploding)
        try:
            result = probes.readyz()
            self.assertFalse(result.ok)
            self.assertEqual(result.http_status, 503)
            self.assertEqual(result.status, "not_ready")
            self.assertIn("RuntimeError", result.checks["chaos_injected"])
        finally:
            probes._READY_CHECKS.clear()

    def test_probe_payloads_are_canonical_json(self):
        blob = probes.healthz().to_json()
        self.assertEqual(blob, json.dumps(json.loads(blob), sort_keys=True, separators=(",", ":")))

    def test_probe_determinism_100x(self):
        verdicts = {probes.healthz().to_json() for _ in range(100)}
        self.assertEqual(len(verdicts), 1)
        ready = {probes.readyz().to_json() for _ in range(100)}
        self.assertEqual(len(ready), 1)


class ProbeServerTests(unittest.TestCase):
    def test_http_endpoints_under_concurrent_burst(self):
        server, _ = probes.serve("127.0.0.1", 0, background=True)
        port = server.server_address[1]
        try:
            def hit(path):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}{path}", timeout=10
                ) as response:
                    return response.status, json.loads(response.read().decode())

            with ThreadPoolExecutor(max_workers=16) as pool:
                results = list(pool.map(hit, ["/healthz", "/readyz"] * 50))
            self.assertEqual(len(results), 100)
            for status, payload in results:
                self.assertEqual(status, 200)
                self.assertIn(payload["status"], ("ok", "ready"))

            with self.assertRaises(urllib.error.HTTPError) as ctx:
                hit("/does-not-exist")
            self.assertEqual(ctx.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()


class StructuredLoggingTests(unittest.TestCase):
    def test_every_line_is_one_json_object(self):
        stream = io.StringIO()
        logger = jlog.JsonLogger("jittest", stream=stream, clock=lambda: 1.5, run_id="fixed")
        logger.info("provision_start", digest="sha256:abc")
        logger.error("provision_refused", phase="phase2", reason="digest_drift")
        lines = [line for line in stream.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 2)
        for line in lines:
            payload = json.loads(line)
            self.assertEqual(payload["service"], "jittest")
            self.assertEqual(payload["run_id"], "fixed")
            self.assertIn(payload["level"], ("INFO", "ERROR"))

    def test_secrets_are_redacted(self):
        stream = io.StringIO()
        logger = jlog.JsonLogger(stream=stream, run_id="r")
        payload = logger.info("auth", git_auth_token="ghp_supersecret", api_key="k", repo="jittest")
        self.assertEqual(payload["git_auth_token"], "[REDACTED]")
        self.assertEqual(payload["api_key"], "[REDACTED]")
        self.assertEqual(payload["repo"], "jittest")
        self.assertNotIn("ghp_supersecret", stream.getvalue())

    def test_unserialisable_field_never_panics(self):
        stream = io.StringIO()
        logger = jlog.JsonLogger(stream=stream, run_id="r")
        logger.warning("weird", obj=object(), fn=len)
        json.loads(stream.getvalue().strip())

    def test_identical_events_are_byte_identical(self):
        stream = io.StringIO()
        logger = jlog.JsonLogger(stream=stream, clock=lambda: 2.0, run_id="r")
        for _ in range(100):
            logger.info("tick", n=1)
        lines = set(line for line in stream.getvalue().splitlines() if line)
        self.assertEqual(len(lines), 1)

    def test_concurrent_writers_never_interleave(self):
        stream = io.StringIO()
        lock = threading.Lock()

        class Locked:
            def write(self, data):
                with lock:
                    stream.write(data)

            def flush(self):
                pass

        logger = jlog.JsonLogger(stream=Locked(), run_id="r")
        with ThreadPoolExecutor(max_workers=32) as pool:
            list(pool.map(lambda i: logger.info("burst", i=i), range(500)))
        lines = [line for line in stream.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 500)
        for line in lines:
            json.loads(line)


class TracingTests(unittest.TestCase):
    def test_nested_spans_share_trace_id(self):
        tracer = tracing.Tracer("jittest-test")
        with (tracer.span("provision", digest="sha256:a") as outer,
              tracer.span("phase1") as inner):
            self.assertEqual(inner.trace_id, outer.trace_id)
            self.assertEqual(inner.parent_id, outer.span_id)
        self.assertEqual([s.name for s in tracer.finished], ["phase1", "provision"])
        self.assertTrue(all(s.status == "OK" for s in tracer.finished))

    def test_exception_marks_span_error_and_propagates(self):
        tracer = tracing.Tracer("jittest-test")
        with self.assertRaises(ValueError), tracer.span("boom"):
            raise ValueError("chaos")
        span = tracer.finished[-1]
        self.assertEqual(span.status, "ERROR")
        self.assertEqual(span.attributes["exception.type"], "ValueError")

    def test_span_dict_is_json_serialisable(self):
        tracer = tracing.Tracer("jittest-test")
        with tracer.span("unit", k="v"):
            pass
        json.dumps(tracer.finished[-1].to_dict())


class BenchmarkDeterminismTests(unittest.TestCase):
    def test_percentiles_are_nearest_rank_and_exact(self):
        samples = list(range(1, 101))
        self.assertEqual(bench.percentile(samples, 50), 50)
        self.assertEqual(bench.percentile(samples, 95), 95)
        self.assertEqual(bench.percentile(samples, 99), 99)
        self.assertEqual(bench.percentile(samples, 100), 100)
        self.assertEqual(bench.percentile(samples, 0), 1)

    def test_percentile_refuses_empty_input(self):
        with self.assertRaises(ValueError):
            bench.percentile([], 50)

    def test_fixed_seed_produces_identical_workload(self):
        def workload(seen):
            def fn(rng, index):
                seen.append(rng.random())
            return fn

        first, second = [], []
        bench.run_benchmark("det", workload(first), iterations=200, seed=7)
        bench.run_benchmark("det", workload(second), iterations=200, seed=7)
        self.assertEqual(first, second)

    def test_different_seed_diverges(self):
        a, b = [], []
        bench.run_benchmark("a", lambda rng, i: a.append(rng.random()), iterations=50, seed=1)
        bench.run_benchmark("b", lambda rng, i: b.append(rng.random()), iterations=50, seed=2)
        self.assertNotEqual(a, b)

    def test_result_shape_and_ordering(self):
        result = bench.run_benchmark("noop", lambda rng, i: None, iterations=300)
        self.assertEqual(result.iterations, 300)
        self.assertGreater(result.throughput_ops_s, 0)
        self.assertLessEqual(result.p50_ms, result.p95_ms)
        self.assertLessEqual(result.p95_ms, result.p99_ms)
        self.assertLessEqual(result.p99_ms, result.max_ms)
        payload = json.loads(result.to_json())
        self.assertEqual(list(payload), sorted(payload))

    def test_metrics_export_is_byte_reproducible(self):
        import os as _os
        import tempfile
        result = bench.run_benchmark("exp", lambda rng, i: None, iterations=10)
        with tempfile.TemporaryDirectory() as tmp:
            path = _os.path.join(tmp, "nested", "metrics.json")
            first = bench.export_metrics([result], path)
            second = bench.export_metrics([result], path)
            self.assertEqual(first, second)
            self.assertEqual(json.loads(first)["schema"], "jittest.bench/1")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
