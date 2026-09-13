"""Regression tests for post-execution evidence inspection (no live writer)."""
from __future__ import annotations

import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from jittest.outputguard import (
    OutputLimits,
    OutputTrustRefusal,
    assert_unchanged,
    scan_output_tree,
    snapshot_tree,
)


class OutputBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()

    def symlink(self, source, target, directory=False):
        try:
            target.symlink_to(source, target_is_directory=directory)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")

    def test_nested_directories_are_not_hardlinks(self):
        nested = self.evidence / "nested"
        nested.mkdir()
        (nested / "proof.json").write_text("{}")
        scan = scan_output_tree(self.evidence)
        self.assertTrue(scan.ok, scan.violations)
        self.assertEqual((scan.files, scan.total_bytes), (1, 2))

    def test_root_symlink_refuses(self):
        alias = self.root / "alias"
        self.symlink(self.evidence, alias, True)
        self.assertFalse(scan_output_tree(alias).ok)

    def test_walk_error_refuses(self):
        def failed_walk(root, **kwargs):
            if kwargs.get("onerror"):
                kwargs["onerror"](PermissionError("denied"))
            return iter(())
        with patch("jittest.outputguard.os.walk", side_effect=failed_walk):
            scan = scan_output_tree(self.evidence)
        self.assertFalse(scan.ok, "unreadable evidence must not look empty and safe")

    def test_disappearing_entry_is_typed_refusal(self):
        with patch("jittest.outputguard.os.walk", return_value=iter([(str(self.evidence), [], ["gone"])])):
            scan = scan_output_tree(self.evidence)
        with self.assertRaises(OutputTrustRefusal):
            scan.raise_if_bad()

    def test_file_budget_stops_early(self):
        for i in range(20):
            (self.evidence / str(i)).write_text("x")
        scan = scan_output_tree(self.evidence, OutputLimits(max_files=2))
        self.assertFalse(scan.ok)
        self.assertLessEqual(scan.files, 3)

    def test_directory_budget(self):
        for i in range(20):
            (self.evidence / str(i)).mkdir()
        scan = scan_output_tree(self.evidence, OutputLimits(max_entries=2))
        self.assertFalse(scan.ok)
        self.assertIn("too_many_entries", scan.violations)

    def test_invalid_limits(self):
        for kwargs in [{"max_files": -1}, {"max_bytes": -1}, {"max_entries": 0}, {"max_files": True}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                OutputLimits(**kwargs)

    def test_snapshot_rejects_missing_root(self):
        with self.assertRaises(OutputTrustRefusal):
            snapshot_tree(self.root / "missing")

    def test_snapshot_refuses_symlink_without_reading_target(self):
        secret = self.root / "secret"
        secret.write_text("outside")
        self.symlink(secret, self.evidence / "link")
        with self.assertRaises(OutputTrustRefusal):
            snapshot_tree(self.evidence)

    def test_snapshot_streams_without_read_bytes(self):
        (self.evidence / "proof").write_bytes(b"x" * 4096)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("whole-file read")):
            snap = snapshot_tree(self.evidence)
        self.assertEqual(snap["proof"][0], 4096)

    @unittest.skipIf(os.name == "nt", "POSIX permission metadata")
    def test_snapshot_detects_mode_change(self):
        proof = self.evidence / "proof"
        proof.write_text("unchanged content")
        proof.chmod(0o600)
        snap = snapshot_tree(self.evidence)
        proof.chmod(0o700)
        with self.assertRaises(OutputTrustRefusal):
            assert_unchanged(self.evidence, snap)

    def test_snapshot_detects_empty_directory_change(self):
        snap = snapshot_tree(self.evidence)
        (self.evidence / "new").mkdir()
        with self.assertRaises(OutputTrustRefusal):
            assert_unchanged(self.evidence, snap)

    def test_concurrent_independent_scans(self):
        def job(i):
            root = self.root / str(i)
            root.mkdir()
            nested = root / "nested"
            nested.mkdir()
            (nested / "proof").write_text("x" * i)
            result = scan_output_tree(root)
            return result.ok, result.files, result.total_bytes
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(job, range(100)))
        self.assertEqual(results, [(True, 1, i) for i in range(100)])

    def test_snapshot_walk_failure_is_typed(self):
        def failed_walk(root, **kwargs):
            kwargs["onerror"](PermissionError("denied"))
            return iter(())
        with patch("jittest.outputguard.os.walk", side_effect=failed_walk), self.assertRaises(OutputTrustRefusal):
            snapshot_tree(self.evidence)

    def test_snapshot_hardlink_refuses(self):
        target = self.root / "outside"
        target.write_text("secret")
        try:
            os.link(target, self.evidence / "hard")
        except (OSError, NotImplementedError):
            self.skipTest("hardlinks unavailable")
        with self.assertRaises(OutputTrustRefusal):
            snapshot_tree(self.evidence)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_snapshot_fifo_refuses_without_blocking(self):
        os.mkfifo(self.evidence / "pipe")
        with self.assertRaises(OutputTrustRefusal):
            snapshot_tree(self.evidence)

    def test_declared_nested_output_and_zero_budget(self):
        (self.evidence / "nested").mkdir()
        (self.evidence / "nested" / "proof").write_text("{}")
        self.assertTrue(scan_output_tree(self.evidence, declared=("nested", "nested/proof")).ok)
        self.assertFalse(scan_output_tree(self.evidence, OutputLimits(max_bytes=0)).ok)
        self.assertFalse(scan_output_tree(self.evidence, OutputLimits(max_files=0)).ok)
