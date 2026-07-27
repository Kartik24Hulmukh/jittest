"""Regression tests for Defect 30: the measurement gate trusted its own input.

`eval/assert_measured.py` exists for one reason: two benchmark runs finished
`success` in 37 and 32 seconds while measuring nothing, and were believed for a
day. The gate is the instrument that makes that state impossible.

Premortem 2 then found that the instrument itself had the same class of bug it
was built to catch:

  * `{"summary": "nope"}` raised AttributeError instead of failing the run, so a
    malformed results file produced a crash whose cause looked like a harness
    bug rather than an unmeasured run.
  * `{"bugs_measured": -2, "model_requests_total": -3}` passed. Negative counts
    are impossible, and `int(x or 0)` happily accepted them as evidence that
    work had been done.

A gate that can crash, or that can be satisfied by impossible numbers, is not a
gate. These tests assert it fails closed on every malformed shape and passes on
exactly one thing: a run that actually issued model requests.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parents[1] / "eval" / "assert_measured.py"


def run_gate(payload, raw=None):
    """Run the real gate script on a temporary results file."""
    path = Path(tempfile.mkdtemp()) / "results.json"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, default=str), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GATE), str(path)],
        capture_output=True, text=True, errors="replace", timeout=120,
    )
    return proc.returncode, proc.stdout + proc.stderr


GOOD = {
    "summary": {
        "bugs_attempted": 5,
        "bugs_measured": 4,
        "model_requests_total": 31,
        "catch_rate": 0.25,
    },
    "results": [],
}


class TestGateFailsClosed(unittest.TestCase):
    """Every unusable or impossible input must exit non-zero without a crash."""

    def assert_rejected(self, label, payload=None, raw=None):
        rc, out = run_gate(payload, raw=raw)
        self.assertNotIn("Traceback (most recent call last)", out,
                         f"{label}: gate crashed instead of failing cleanly")
        self.assertEqual(rc, 1, f"{label}: gate accepted an unmeasured run")

    def test_string_summary(self):
        self.assert_rejected("string summary", {"summary": "nope"})

    def test_list_summary(self):
        self.assert_rejected("list summary", {"summary": [1, 2]})

    def test_null_summary(self):
        self.assert_rejected("null summary", {"summary": None})

    def test_top_level_not_an_object(self):
        self.assert_rejected("string payload", "just a string")
        self.assert_rejected("list payload", [1, 2, 3])

    def test_empty_object(self):
        self.assert_rejected("empty object", {})

    def test_missing_counts(self):
        self.assert_rejected("missing keys", {"summary": {}})

    def test_zero_model_requests(self):
        self.assert_rejected("zero requests", {"summary": {
            "bugs_attempted": 5, "bugs_measured": 0, "model_requests_total": 0}})

    def test_negative_counts_are_impossible(self):
        self.assert_rejected("negative counts", {"summary": {
            "bugs_attempted": -1, "bugs_measured": -2,
            "model_requests_total": -3}})

    def test_nan_request_count(self):
        self.assert_rejected("nan requests", {"summary": {
            "bugs_attempted": 5, "bugs_measured": 2,
            "model_requests_total": float("nan")}})

    def test_boolean_request_count(self):
        self.assert_rejected("bool requests", {"summary": {
            "bugs_attempted": 5, "bugs_measured": 2,
            "model_requests_total": True}})

    def test_string_request_count(self):
        self.assert_rejected("string requests", {"summary": {
            "bugs_attempted": 5, "bugs_measured": 2,
            "model_requests_total": "lots"}})

    def test_measured_exceeds_attempted(self):
        self.assert_rejected("measured > attempted", {"summary": {
            "bugs_attempted": 2, "bugs_measured": 9,
            "model_requests_total": 10}})

    def test_catch_rate_out_of_range(self):
        self.assert_rejected("catch_rate 7.5", {"summary": {
            "bugs_attempted": 5, "bugs_measured": 4,
            "model_requests_total": 31, "catch_rate": 7.5}})

    def test_unparseable_json(self):
        self.assert_rejected("broken json", raw="{not json at all")

    def test_missing_file(self):
        proc = subprocess.run(
            [sys.executable, str(GATE), "/nonexistent/results.json"],
            capture_output=True, text=True, errors="replace", timeout=120,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("Traceback (most recent call last)", proc.stderr)


class TestGatePassesOnlyRealMeasurement(unittest.TestCase):
    """The one shape that may pass, and proof it is not passing vacuously."""

    def test_measured_run_passes(self):
        rc, out = run_gate(GOOD)
        self.assertEqual(rc, 0, out)
        self.assertIn("4/5 bugs measured across 31 model requests", out)

    def test_not_measured_reasons_are_surfaced(self):
        payload = {
            "summary": {"bugs_attempted": 2, "bugs_measured": 0,
                        "model_requests_total": 0},
            "results": [
                {"status": "not_measured", "error": "empty diff between base and head"},
                {"status": "not_measured", "error": "clone failed"},
            ],
        }
        rc, out = run_gate(payload)
        self.assertEqual(rc, 1)
        self.assertIn("empty diff between base and head", out)
        self.assertIn("clone failed", out)

    def test_malformed_result_rows_do_not_crash_reason_reporting(self):
        payload = {
            "summary": {"bugs_attempted": 1, "bugs_measured": 0,
                        "model_requests_total": 0},
            "results": ["not a dict", None, 42],
        }
        rc, out = run_gate(payload)
        self.assertEqual(rc, 1)
        self.assertNotIn("Traceback (most recent call last)", out)


if __name__ == "__main__":
    unittest.main()
