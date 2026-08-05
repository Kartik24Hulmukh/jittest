"""Tests for strict boolean environment parsing and candidate persistence controls."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest._pipeline_helpers import _telemetry, persist_candidate_source
from jittest.cli import build_parser
from jittest.config import load_config, parse_bool
from jittest.results import Report


class StrictBooleanConfigTests(unittest.TestCase):
    def test_parse_bool_true_values(self):
        for val in ("1", "true", "TRUE", "yes", "YES", "on", "ON", True, 1):
            parsed, note = parse_bool(val, default=False)
            self.assertTrue(parsed, f"expected True for {val!r}")
            self.assertIsNone(note)

    def test_parse_bool_false_values(self):
        for val in ("0", "false", "FALSE", "no", "NO", "off", "OFF", False, 0):
            parsed, note = parse_bool(val, default=True)
            self.assertFalse(parsed, f"expected False for {val!r}")
            self.assertIsNone(note)

    def test_parse_bool_invalid_values_fallback_and_note(self):
        for val in ("maybe", "invalid", "2", "Trueish"):
            parsed, note = parse_bool(val, default=True, key="persist_candidates")
            self.assertTrue(parsed, f"expected fallback default True for {val!r}")
            self.assertIsNotNone(note)
            self.assertIn("not a valid boolean", note)

    def test_env_zero_disables_persistence(self):
        with mock.patch.dict(os.environ, {"JITTEST_PERSIST_CANDIDATES": "0"}):
            cfg = load_config(".")
            self.assertFalse(cfg.persist_candidates)

    def test_env_false_disables_persistence(self):
        with mock.patch.dict(os.environ, {"JITTEST_PERSIST_CANDIDATES": "false"}):
            cfg = load_config(".")
            self.assertFalse(cfg.persist_candidates)

    def test_env_one_enables_persistence(self):
        with mock.patch.dict(os.environ, {"JITTEST_PERSIST_CANDIDATES": "1"}):
            cfg = load_config(".")
            self.assertTrue(cfg.persist_candidates)

    def test_invalid_text_does_not_silently_become_true(self):
        with mock.patch.dict(os.environ, {"JITTEST_PERSIST_CANDIDATES": "invalid_text"}):
            cfg = load_config(".")
            self.assertTrue(cfg.persist_candidates)  # default fallback
            self.assertTrue(any("not a valid boolean" in note for note in cfg.notes))

    def test_cli_no_persist_candidates_overrides_env_and_config(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--no-persist-candidates"])
        self.assertFalse(args.persist_candidates)

        with mock.patch.dict(os.environ, {"JITTEST_PERSIST_CANDIDATES": "1"}):
            cfg = load_config(".", overrides={"persist_candidates": args.persist_candidates})
            self.assertFalse(cfg.persist_candidates)

    def test_disabled_persistence_returns_sha256_and_empty_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            text = "def test_foo(): pass"
            sha256, path = persist_candidate_source(text, candidate_dir=tmpdir, enabled=False)
            self.assertTrue(len(sha256) == 64)
            self.assertEqual(path, "")
            # Verify no file created on disk
            files = list(Path(tmpdir).rglob("*.py"))
            self.assertEqual(len(files), 0)

    def test_telemetry_contains_no_candidate_path_when_disabled(self):
        rep = Report(repo=".", base="main", head="HEAD", model="claude")
        target = mock.Mock(symbol="target_foo", file_path="src/foo.py")
        rs = mock.Mock(score=0.5)

        _telemetry(rep, target, rs, attempt=1, disposition="syntax_error",
                   candidate_source_sha256="abc123sha", candidate_source_path="")

        self.assertEqual(len(rep.telemetry), 1)
        tel = rep.telemetry[0]
        self.assertEqual(tel.candidate_source_sha256, "abc123sha")
        self.assertEqual(tel.candidate_source_path, "")
        self.assertEqual(tel.as_dict()["candidate_source_path"], "")


if __name__ == "__main__":
    unittest.main()
