"""Operational probes: deterministic state, bounded memory, real socket faults."""
from __future__ import annotations

import gc
import io
import json
import logging
import random
import socket
import subprocess
import sys
import threading
import tracemalloc
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError
from urllib.request import urlopen
from wsgiref.simple_server import WSGIRequestHandler, make_server

from jittest.integrity import build_integrity_record, compare_runs
from jittest.prod import ProbeApp


def request(app, path="/readyz", method="GET"):
    capture = []
    body = b"".join(app({"PATH_INFO": path, "REQUEST_METHOD": method},
                        lambda status, headers: capture.append((status, dict(headers)))))
    return capture[0][0], capture[0][1], body


class QuietHandler(WSGIRequestHandler):
    def log_message(self, *args):
        pass


class ProbeTests(unittest.TestCase):
    def test_lifecycle_fail_closed_and_drain_is_terminal(self):
        app = ProbeApp()
        self.assertEqual(request(app)[0], "503 Service Unavailable")
        self.assertEqual(request(app, "/healthz")[0], "200 OK")
        app.set_ready(True)
        self.assertEqual(request(app)[2], b'{"status":"ready"}')
        app.drain()
        app.set_ready(True)
        self.assertEqual(request(app)[0], "503 Service Unavailable")
        self.assertEqual(request(app, "/healthz")[0], "200 OK")
        with self.assertRaises(TypeError):
            app.set_ready("yes")

    def test_http_contract(self):
        app = ProbeApp()
        status, headers, body = request(app, method="HEAD")
        self.assertTrue(status.startswith("503"))
        self.assertEqual(body, b"")
        self.assertEqual(int(headers["Content-Length"]), len(request(app)[2]))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertTrue(request(app, "/unknown")[0].startswith("404"))
        self.assertEqual(request(app, method="POST")[1]["Allow"], "GET, HEAD")

    def test_json_logs_redact_untrusted_path_and_trace(self):
        output = io.StringIO()
        logger = logging.Logger("probe-test", logging.INFO)
        logger.addHandler(logging.StreamHandler(output))
        tracer = MagicMock()
        app = ProbeApp(logger=logger, tracer=tracer)
        request(app, "/secret-token?" + "pass" + "word=do-not-log")
        record = json.loads(output.getvalue())
        self.assertEqual(record["route"], "unmatched")
        self.assertNotIn("secret", output.getvalue())
        tracer.start_as_current_span.assert_called_once_with("jittest.probe")
        span = tracer.start_as_current_span.return_value.__enter__.return_value
        span.set_attribute.assert_any_call("http.route", "unmatched")

    def test_telemetry_outage_does_not_change_verdict(self):
        tracer = Mock()
        tracer.start_as_current_span.side_effect = OSError("exporter unavailable")
        app = ProbeApp(tracer=tracer)
        self.assertTrue(request(app)[0].startswith("503"))
        app.set_ready(True)
        self.assertTrue(request(app)[0].startswith("200"))

    def test_seeded_100x_burst_out_of_order_drain(self):
        app = ProbeApp()
        app.set_ready(True)
        order = list(range(10000))
        random.Random(20260913).shuffle(order)
        def one(i):
            if i % 7 == 0:
                app.set_ready(True)
            if i == 500:
                app.drain()
            return request(app)[0]
        with ThreadPoolExecutor(max_workers=32) as pool:
            results = list(pool.map(one, order))
        self.assertEqual(len(results), 10000)
        self.assertLessEqual(set(results), {"200 OK", "503 Service Unavailable"})
        self.assertTrue(request(app)[0].startswith("503"))

    def test_repeated_requests_do_not_accumulate_state(self):
        app = ProbeApp()
        for _ in range(100):
            request(app)
        gc.collect()
        tracemalloc.start()
        try:
            before = tracemalloc.get_traced_memory()[0]
            for _ in range(10000):
                request(app)
            gc.collect()
            retained = tracemalloc.get_traced_memory()[0] - before
            self.assertLess(retained, 128 * 1024)
        finally:
            tracemalloc.stop()

    def test_real_http_io_drop_and_recovery(self):
        app = ProbeApp()
        with make_server("127.0.0.1", 0, app, handler_class=QuietHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as exc:
                    urlopen(url + "/readyz", timeout=3)
                self.assertEqual(exc.exception.code, 503)
                exc.exception.close()
                # Drop the peer after submitting a request; next probe recovers.
                with socket.create_connection(server.server_address, timeout=3) as peer:
                    peer.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
                app.set_ready(True)
                with urlopen(url + "/readyz", timeout=3) as response:
                    self.assertEqual(response.status, 200)
            finally:
                server.shutdown()
                thread.join(timeout=3)
            self.assertFalse(thread.is_alive())

    def test_process_kill_restart_defaults_not_ready(self):
        script = "from jittest.prod import ProbeApp; import time; a=ProbeApp(); a.set_ready(True); print('ready',flush=True); time.sleep(30)"
        child = subprocess.Popen([sys.executable, "-u", "-c", script], stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            child.kill()
            child.wait(timeout=5)
            self.assertNotEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
            child.stdout.close()
        # Restart explicitly reinitializes; no stale persisted ready bit.
        script = "from jittest.prod import ProbeApp; a=ProbeApp(); print(b''.join(a({'PATH_INFO':'/readyz'},lambda *a:None)).decode())"
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(json.loads(result.stdout), {"status": "not_ready"})

    def test_integrity_comparison_preserves_exact_contract(self):
        a = build_integrity_record(b"x", "sha256:" + "ab" * 32, "", "none", [], 0, b"ok")
        b = build_integrity_record(b"x", "sha256:" + "ab" * 32, "", "none", [], 0, b"bad")
        same = compare_runs(a, a)
        self.assertTrue(same["reproducible"])
        self.assertEqual(same["first_digest"], a.digest())
        self.assertEqual(compare_runs(a, b)["differences"], ["output_sha256"])


class IntegrationHardeningTests(unittest.TestCase):
    def test_span_history_is_bounded_and_concurrent_roots_independent(self):
        from jittest.prod.tracing import Tracer
        tracer = Tracer(max_finished=8)
        barrier = threading.Barrier(16)
        def one(i):
            with tracer.span("root") as root:
                barrier.wait(timeout=5)
                with tracer.span("child") as child:
                    self.assertEqual(child.parent_id, root.span_id)
                    return root.parent_id, root.trace_id
        with ThreadPoolExecutor(max_workers=16) as pool:
            values = list(pool.map(one, range(16)))
        self.assertTrue(all(parent is None for parent, _ in values))
        self.assertEqual(len({trace for _, trace in values}), 16)
        self.assertEqual(len(tracer.finished), 8)

    def test_real_sdk_receives_probe_and_compatibility_spans(self):
        try:
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
        except ImportError:
            self.skipTest("optional OpenTelemetry SDK not installed")
        from jittest.prod.tracing import Tracer
        provider = TracerProvider()
        exporter = InMemorySpanExporter()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        try:
            tracer = provider.get_tracer("test")
            request(ProbeApp(tracer=tracer))
            compatibility = Tracer()
            compatibility._otel = tracer
            with compatibility.span("pipeline", phase="fetch"):
                pass
            spans = exporter.get_finished_spans()
            self.assertEqual([s.name for s in spans], ["jittest.probe", "pipeline"])
            self.assertEqual(spans[0].attributes["http.response.status_code"], 503)
            self.assertEqual(spans[1].attributes["phase"], "fetch")
        finally:
            provider.shutdown()

    def test_nested_secret_fields_redacted(self):
        from jittest.prod.logging import JsonLogger
        logger = JsonLogger(stream=io.StringIO())
        record = logger.record("info", "request", data={"items": [{"authorization": "secret"}]})
        self.assertEqual(record["data"]["items"][0]["authorization"], "[REDACTED]")


class BenchmarkAccountingTests(unittest.TestCase):
    def test_completed_spans_not_confused_with_retention(self):
        from scripts.bench_100x import concurrency_invariant
        result = concurrency_invariant(jobs=1100, workers=8)
        self.assertEqual(result["spans_closed"], 1100)
        self.assertEqual(result["spans_retained"], 1024)
        self.assertEqual(result["unhandled_panics"], 0)
