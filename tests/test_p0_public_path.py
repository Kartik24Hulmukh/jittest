"""Adversarial tests for the P0 state machine on the public verify path."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest import verify as V


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)
        self.addCleanup(self._d.cleanup)

    def env(self, **kw):
        p = mock.patch.dict(os.environ, kw, clear=False)
        p.start()
        self.addCleanup(p.stop)


class Readiness(_Tmp):
    def test_absent_without_requirements(self):
        self.assertIsNone(V._readiness_block(self.tmp, {"resolved_versions": {}}))

    def test_observes_missing_dependency(self):
        self.env(JITTEST_READINESS="observe")
        (self.tmp / "requirements.txt").write_text("flask==3.0.0", encoding="utf-8")
        b = V._readiness_block(self.tmp, {"resolved_versions": {}})
        self.assertTrue(b["evaluated"])
        self.assertFalse(b["ok"])
        self.assertTrue(any(p.startswith("missing_direct_dependency") for p in b["problems"]))

    def test_ok_when_target_has_dependency(self):
        self.env(JITTEST_READINESS="required")
        (self.tmp / "requirements.txt").write_text("flask==3.0.0", encoding="utf-8")
        self.assertTrue(V._readiness_block(self.tmp, {"resolved_versions": {"flask": "3.0.0"}})["ok"])

    def test_refuses_fail_closed_when_required(self):
        self.env(JITTEST_READINESS="required")
        (self.tmp / "requirements.txt").write_text("flask==3.0.0", encoding="utf-8")
        with self.assertRaises(V.VerifyRefusalError) as ctx:
            V._readiness_block(self.tmp, {"resolved_versions": {}})
        self.assertEqual(ctx.exception.reason.code, "environment_not_ready")


class OutputGuard(_Tmp):
    def test_clean_tree(self):
        self.env(JITTEST_OUTPUT_GUARD="observe")
        (self.tmp / "a.txt").write_text("hello", encoding="utf-8")
        b = V._output_guard_block(self.tmp)
        self.assertTrue(b["scanned"])
        self.assertTrue(b["ok"])
        self.assertGreaterEqual(b["files"], 1)

    def _escape(self):
        out = self.tmp / "x.txt"
        out.write_text("s", encoding="utf-8")
        tree = self.tmp / "tree"
        tree.mkdir()
        try:
            (tree / "escape").symlink_to(out)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation not permitted here")
        return tree

    def test_observes_symlink_escape(self):
        self.env(JITTEST_OUTPUT_GUARD="observe")
        b = V._output_guard_block(self._escape())
        self.assertTrue(b["scanned"])
        self.assertFalse(b["ok"])
        self.assertTrue(b["violations"])

    def test_refuses_fail_closed_when_required(self):
        self.env(JITTEST_OUTPUT_GUARD="required")
        tree = self._escape()
        with self.assertRaises(V.VerifyRefusalError) as ctx:
            V._output_guard_block(tree)
        self.assertEqual(ctx.exception.reason.code, "output_boundary_violation")

    def test_missing_tree_never_crashes(self):
        self.assertIsNotNone(V._output_guard_block(self.tmp / "nope"))


class EnforcementErrors(_Tmp):
    def test_freeze_list_is_actual_provisioner_contract(self):
        self.env(JITTEST_READINESS="required")
        (self.tmp / "requirements.txt").write_text("Flask==3.0.0", encoding="utf-8")
        block = V._readiness_block(self.tmp, {"resolved_versions": ["Flask==3.0.0"]})
        self.assertTrue(block["ok"])

    def test_readiness_exception_refuses_when_required(self):
        self.env(JITTEST_READINESS="required")
        (self.tmp / "requirements.txt").write_text("flask", encoding="utf-8")
        with (mock.patch("jittest.readiness.evaluate_readiness", side_effect=RuntimeError("broken")),
              self.assertRaises(V.VerifyRefusalError)):
            V._readiness_block(self.tmp, {})

    def test_output_exception_refuses_when_required(self):
        self.env(JITTEST_OUTPUT_GUARD="required")
        with (mock.patch("jittest.outputguard.scan_output_tree", side_effect=RuntimeError("broken")),
              self.assertRaises(V.VerifyRefusalError)):
            V._output_guard_block(self.tmp)

    def test_oversized_requirements_are_not_silently_truncated(self):
        self.env(JITTEST_READINESS="required")
        (self.tmp / "requirements.txt").write_bytes(b"#" * 200_001)
        with self.assertRaises(V.VerifyRefusalError):
            V._readiness_block(self.tmp, {})

    def test_symlink_requirements_refuse_without_reading_target(self):
        self.env(JITTEST_READINESS="required")
        target = self.tmp / "secret"
        target.write_text("", encoding="utf-8")
        try:
            (self.tmp / "requirements.txt").symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaises(V.VerifyRefusalError):
            V._readiness_block(self.tmp, {})

    def test_fifo_requirements_refuse_without_opening(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("FIFO unsupported")
        self.env(JITTEST_READINESS="required")
        os.mkfifo(self.tmp / "requirements.txt")
        with self.assertRaises(V.VerifyRefusalError):
            V._readiness_block(self.tmp, {})

    def test_observe_records_error_without_claiming_ok(self):
        self.env(JITTEST_OUTPUT_GUARD="observe")
        with mock.patch("jittest.outputguard.scan_output_tree", side_effect=RuntimeError("secret")):
            block = V._output_guard_block(self.tmp)
        self.assertFalse(block["scanned"])
        self.assertNotIn("ok", block)
        self.assertNotIn("secret", str(block))


def _integ(**over):
    kw = dict(
        test_code="def test_x():\\n    assert True",
        sandbox_dict={"backend": "none"},
        env_info={"resolved_versions": {"pytest": "8.0.0"}},
        command=["jittest", "verify"],
        exit_code=0,
        output_material="deadbeef",
        incomplete=False,
        non_reproducible=False,
    )
    kw.update(over)
    return V._integrity_block(**kw)


class Integrity(unittest.TestCase):
    def test_deterministic(self):
        a, b = _integ(), _integ()
        self.assertEqual(a, b)
        self.assertEqual(a["schema_version"], "integrity-1.0")
        self.assertEqual(len(a["record_digest"]), 64)

    def test_binds_source(self):
        self.assertNotEqual(_integ()["record_digest"], _integ(test_code="x = 1")["record_digest"])

    def test_flags(self):
        self.assertTrue(_integ(non_reproducible=True)["reproducibility_note"])
        self.assertTrue(_integ(incomplete=True)["incomplete"])


if __name__ == "__main__":
    unittest.main()
