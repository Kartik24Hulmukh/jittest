"""Regression tests for defects uncovered by human-perspective chaos testing.

Defects:
1. Impatient canceller (RST mid-request) caused ConnectionResetError / BrokenPipeError
   in BaseHTTPRequestHandler.finish() when flushing wfile, leaking tracebacks to stderr.
2. register_readiness_check blindly appended duplicates, risking permanent 503 or
   duplicate probe execution.
"""

from __future__ import annotations

import io
import socket
import struct
import sys
import unittest

from jittest.prod import probes


class TestHumanChaosRegressions(unittest.TestCase):
    def tearDown(self):
        probes.unregister_readiness_check("test_check")
        probes.unregister_readiness_check("test_check_2")

    def test_guarded_finish_present(self):
        self.assertTrue(hasattr(probes._Handler, "finish"))

    def test_readiness_registration_idempotent(self):
        initial_count = len(probes._READY_CHECKS)
        probes.register_readiness_check("test_check", lambda: None)
        self.assertEqual(len(probes._READY_CHECKS), initial_count + 1)

        # Register again with same name
        probes.register_readiness_check("test_check", lambda: None)
        self.assertEqual(len(probes._READY_CHECKS), initial_count + 1)

    def test_readiness_registration_replacement(self):
        called = []
        probes.register_readiness_check("test_check", lambda: called.append("v1"))
        res = probes.readyz()
        self.assertTrue(res.ok)
        self.assertEqual(called, ["v1"])

        # Replace with failing check
        probes.register_readiness_check("test_check", lambda: (_ for _ in ()).throw(ValueError("boom")))
        res2 = probes.readyz()
        self.assertFalse(res2.ok)
        self.assertEqual(res2.http_status, 503)
        self.assertIn("failed: ValueError", res2.checks["test_check"])
        # v1 was not called again
        self.assertEqual(called, ["v1"])

    def test_readiness_registration_distinct_names(self):
        initial_count = len(probes._READY_CHECKS)
        probes.register_readiness_check("test_check", lambda: None)
        probes.register_readiness_check("test_check_2", lambda: None)
        self.assertEqual(len(probes._READY_CHECKS), initial_count + 2)
        probes.unregister_readiness_check("test_check_2")
        self.assertEqual(len(probes._READY_CHECKS), initial_count + 1)

    def test_rst_storm_stderr_silence(self):
        server, thread = probes.serve("127.0.0.1", 0, background=True)
        host, port = server.server_address[0], server.server_address[1]

        captured = io.StringIO()
        real_stderr = sys.stderr
        sys.stderr = captured
        try:
            for _ in range(25):
                try:
                    s = socket.create_connection((host, port), timeout=2.0)
                    s.sendall(b"GET /healthz HTTP/1.1\r\nHost: localhost\r\n")
                    # Force hard RST with SO_LINGER on close
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    s.close()
                except OSError:
                    pass

            self.assertTrue(probes.healthz().ok)
        finally:
            sys.stderr = real_stderr
            server.shutdown()
            thread.join(timeout=3)

        stderr_output = captured.getvalue()
        self.assertNotIn("Traceback", stderr_output)
        self.assertNotIn("ConnectionResetError", stderr_output)


if __name__ == "__main__":
    unittest.main()
