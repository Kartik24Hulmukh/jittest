"""Owned probe stubs test diagnostic plumbing, not container confinement."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jittest import execute as E
from jittest.sandbox import SandboxPlan

PIN = "localhost:5000/owned-probe@sha256:" + "a" * 64


class IsolatedProbeDiagnostics(unittest.TestCase):
    def test_nonzero_probe_preserves_observed_failure_in_sandbox_notes(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            with (
                patch.dict("os.environ", {"JITTEST_FORCE_MINIRUNNER": ""}),
                patch.object(E, "_run_process", return_value=(17, "owned probe stdout", "owned probe stderr")),
            ):
                runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
            self.assertEqual(runner, ["python", "-m", "jittest._minirunner"])
            self.assertIn("owned probe stdout", "\n".join(sbx.notes))
            self.assertIn("owned probe stderr", "\n".join(sbx.notes))

    @staticmethod
    def _note(sbx):
        notes = [n for n in sbx.notes if n.startswith(E._PROBE_NOTE_PREFIX)]
        return json.loads(notes[-1][len(E._PROBE_NOTE_PREFIX):])

    def test_nonzero_full_available_hashes_and_probe_timeout_argv_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(
                    E, "_run_process", return_value=(23, "owned full stdout", "owned full stderr")) as proc:
                runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=90, python_path="owned-python")
            note = self._note(sbx)
            self.assertEqual(note["reason"], "nonzero_exit")
            self.assertEqual(note["returncode"], 23)
            self.assertEqual(note["stdout"]["sha256"], hashlib.sha256(b"owned full stdout").hexdigest())
            self.assertEqual(note["stderr"]["sha256"], hashlib.sha256(b"owned full stderr").hexdigest())
            self.assertEqual(note["stdout"]["sha256_of"], "utf8_rendered_text")
            self.assertEqual(proc.call_args.args[-1], 10)
            argv = proc.call_args.args[0]
            self.assertEqual(argv[-5:], ["python", "-I", "-m", "pytest", "--version"])
            self.assertEqual(runner, ["owned-python", "-m", "jittest._minirunner"])

    def test_timeout_available_raw_byte_streams_are_hashed_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            token = "sk-" + "a" * 32
            stdout = ("owned timeout " + token).encode() + b"\xff"
            stderr = b"owned timeout stderr"
            error = subprocess.TimeoutExpired(["owned-probe"], 5, output=stdout, stderr=stderr)
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(
                    E, "_run_process", side_effect=error):
                runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
            note = self._note(sbx)
            self.assertEqual(note["reason"], "timeout")
            self.assertIsNone(note["returncode"])
            self.assertEqual(note["stdout"]["sha256"], hashlib.sha256(stdout).hexdigest())
            self.assertEqual(note["stdout"]["sha256_of"], "raw_bytes")
            self.assertEqual(note["stdout"]["bytes"], len(stdout))
            self.assertEqual(note["stderr"]["sha256"], hashlib.sha256(stderr).hexdigest())
            self.assertNotIn(token, "".join(sbx.notes))
            self.assertIn("[redacted by jittest]", note["stdout"]["excerpt"])
            self.assertEqual(runner, ["python", "-m", "jittest._minirunner"])

    def test_timeout_absent_streams_are_unavailable_not_fabricated_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(
                    E, "_run_process", side_effect=subprocess.TimeoutExpired(["owned-probe"], 5)):
                E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
            self.assertEqual(self._note(sbx)["stdout"], {"available": False})
            self.assertEqual(self._note(sbx)["stderr"], {"available": False})

    def test_os_error_is_observed_redacted_and_does_not_change_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            error = FileNotFoundError("owned missing runtime; API_KEY=owned-fake-secret")
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(
                    E, "_run_process", side_effect=error):
                runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
            note = self._note(sbx)
            self.assertEqual(note["reason"], "os_error")
            self.assertEqual(note["error_type"], "FileNotFoundError")
            self.assertIsNone(note["returncode"])
            self.assertNotIn("owned-fake-secret", "".join(sbx.notes))
            self.assertEqual(runner, ["python", "-m", "jittest._minirunner"])

    def test_success_probe_does_not_add_failure_note_or_change_pytest_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN, notes=["owned backend note"])
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(
                    E, "_run_process", return_value=(0, "owned pytest version", "")):
                runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
            self.assertEqual(runner, ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"])
            self.assertEqual(sbx.notes, ["owned backend note"])

    def test_forced_and_stock_paths_still_do_not_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            for image, forced in (("", ""), (PIN, "1")):
                with self.subTest(image=image, forced=forced):
                    sbx = SandboxPlan(backend="docker", runtime_image=image)
                    with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": forced}), patch.object(E, "_run_process") as proc:
                        runner = E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
                    proc.assert_not_called()
                    self.assertEqual(runner, ["python", "-m", "jittest._minirunner"])
                    self.assertEqual(sbx.notes, [])

    def test_only_expected_probe_failures_are_caught(self):
        with tempfile.TemporaryDirectory() as temporary:
            for error in (RuntimeError("owned programmer error"), KeyboardInterrupt()):
                with self.subTest(error=type(error).__name__):
                    sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
                    with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(E, "_run_process", side_effect=error), self.assertRaises(type(error)):
                        E.detect_isolated_runner(Path(temporary), sbx, timeout_s=5)
                    self.assertEqual(sbx.notes, [])

    def test_redaction_precedes_excerpt_boundary_and_serialized_budget_is_bounded(self):
        token = "sk-" + "a" * 32
        stdout = "p" * 590 + " " + token + " " + "q" * 5000
        stderr = "\x00\u2028\U0001f600" * 2000
        sbx = SandboxPlan(notes=["owned existing backend note"])
        for _ in range(40):
            E._note_isolated_probe_failure(sbx, "nonzero_exit", 17, stdout, stderr)
        self.assertEqual(sbx.notes[0], "owned existing backend note")
        self.assertEqual(len(sbx.notes), 17)
        for note in sbx.notes[1:]:
            self.assertLessEqual(len(note), 2500)
            self.assertNotIn(token[:9], note)
            payload = json.loads(note[len(E._PROBE_NOTE_PREFIX):])
            self.assertTrue(payload["stdout"]["excerpt_truncated"])
            self.assertTrue(payload["stderr"]["excerpt_truncated"])
            self.assertEqual(payload["stdout"]["sha256"], hashlib.sha256(stdout.encode()).hexdigest())
            self.assertEqual(payload["stderr"]["sha256"], hashlib.sha256(stderr.encode()).hexdigest())
        self.assertEqual(sbx.as_dict()["notes"], sbx.notes)

    def test_probe_streams_do_not_contaminate_actual_test_output_or_classification(self):
        for rc, expected in ((1, E.Outcome.FAIL), (2, E.Outcome.ERROR), (5, E.Outcome.NOTRUN)):
            with self.subTest(rc=rc), tempfile.TemporaryDirectory() as temporary:
                sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
                results = [(17, "owned probe stdout", "owned probe stderr"),
                           (rc, "owned test stdout", "AssertionError: owned test stderr")]
                with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(E, "_run_process", side_effect=results) as proc:
                    result = E.run_test(Path(temporary), "def test_owned(): assert False\n", sbx=sbx)
                self.assertEqual(proc.call_count, 2)
                self.assertIs(result.outcome, expected)
                self.assertEqual(result.stdout, "owned test stdout")
                self.assertEqual(result.stderr, "AssertionError: owned test stderr")
                self.assertNotIn("owned probe", result.tail)
                self.assertIn("owned probe", "".join(sbx.notes))

    def test_actual_owned_process_timeout_preserves_streams_on_same_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            command = [sys.executable, "-S", "-c", "import sys,time; print('owned stdout',flush=True); print('owned stderr',file=sys.stderr,flush=True); time.sleep(60)"]
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                E._run_process(command, temporary, {k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ}, 2)
            self.assertIn(b"owned stdout", caught.exception.stdout)
            self.assertIn(b"owned stderr", caught.exception.stderr)

    def test_timeout_test_result_still_reports_timeout_without_probe_stream_mix(self):
        with tempfile.TemporaryDirectory() as temporary:
            sbx = SandboxPlan(backend="docker", runtime_image=PIN, image=PIN)
            probe_error = subprocess.TimeoutExpired(["owned-probe"], 5, output=b"probe-only")
            test_error = subprocess.TimeoutExpired(["owned-test"], 5, output=b"test-only")
            with patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": ""}), patch.object(E, "_run_process", side_effect=[probe_error, test_error]):
                result = E.run_test(Path(temporary), "def test_owned(): assert False\n", sbx=sbx, timeout_s=5)
            self.assertIs(result.outcome, E.Outcome.TIMEOUT)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "timed out after 5s")
            self.assertIn("probe-only", "".join(sbx.notes))
            self.assertNotIn("test-only", "".join(sbx.notes))

    def test_large_exception_metadata_cannot_escape_note_size_budget(self):
        error_type = type("Owned" + "\U0001f600" * 4000, (OSError,), {})
        sbx = SandboxPlan()
        E._note_isolated_probe_failure(sbx, "os_error", None, error=error_type("\x00" * 5000))
        self.assertEqual(len(sbx.notes), 1)
        self.assertLessEqual(len(sbx.notes[0]), 2500)
        note = self._note(sbx)
        self.assertEqual(note["reason"], "os_error")
        self.assertLessEqual(len(note["error_type"]), 80)
        self.assertIsNone(note["returncode"])


if __name__ == "__main__":
    unittest.main()
