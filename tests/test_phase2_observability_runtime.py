"""Phase-2 tasks 27 + 18-23: observability fields and Option C plumbing.

Pins the additive telemetry/report keys (refusal.code, sandbox backend and
image digest, wall clock) and the trusted-runtime-image resolution rules
from docs/RUNTIME-IMAGES.md: digest pinning (Rule 1) and base-branch
precedence over a head-branch modification (Rule 2).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest import sandbox
from jittest.results import CandidateTelemetry, Report

PIN = "python:3.12-slim@sha256:" + "ab" * 32


class ObservabilityFieldsTest(unittest.TestCase):
    def test_telemetry_carries_the_new_observability_keys(self):
        d = CandidateTelemetry().as_dict()
        for key in ("refusal_code", "sandbox_backend",
                    "sandbox_image_digest", "wall_clock_s"):
            self.assertIn(key, d)
        self.assertEqual(d["refusal_code"], "")
        self.assertEqual(d["wall_clock_s"], 0.0)
        self.assertTrue(json.dumps(d, allow_nan=False))

    def test_report_exposes_wall_clock_and_phases(self):
        d = Report(repo="r", base="b", head="h", model="m").as_dict()
        self.assertIn("wall_clock_s", d)
        self.assertIn("phases", d)
        self.assertTrue(json.dumps(d, allow_nan=False))


class ImageRefValidationTest(unittest.TestCase):
    def test_digest_pinned_reference_is_accepted(self):
        ok, err = sandbox.validate_image_ref(PIN)
        self.assertTrue(ok, err)

    def test_tag_only_reference_is_rejected(self):
        ok, err = sandbox.validate_image_ref("python:3.12-slim")
        self.assertFalse(ok)
        self.assertIn("sha256", err)

    def test_empty_reference_is_rejected(self):
        self.assertFalse(sandbox.validate_image_ref("")[0])


class RuntimeImageResolutionTest(unittest.TestCase):
    def _git(self, repo, *args):
        subprocess.run(["git", "-C", str(repo), *args], check=True,
                       capture_output=True)

    def test_base_branch_wins_over_head_modification(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            self._git(repo, "init", "-q", "-b", "main")
            self._git(repo, "config", "user.email", "t@t")
            self._git(repo, "config", "user.name", "t")
            (repo / "pyproject.toml").write_text(
                f'[tool.jittest.runtime]\nimage = "{PIN}"\n')
            self._git(repo, "add", ".")
            self._git(repo, "commit", "-qm", "base")
            base = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                capture_output=True, text=True).stdout.strip()
            self._git(repo, "checkout", "-qb", "evil")
            (repo / "pyproject.toml").write_text(
                '[tool.jittest.runtime]\nimage = "evil:latest"\n')
            self._git(repo, "commit", "-qam", "head tries to redirect")
            image, notes = sandbox.load_runtime_image(repo, base)
            self.assertEqual(image, PIN)
            self.assertTrue(any("ignored" in n for n in notes), notes)

    def test_env_var_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            os.environ["JITTEST_RUNTIME_IMAGE"] = PIN
            try:
                image, notes = sandbox.load_runtime_image(Path(td), None)
            finally:
                del os.environ["JITTEST_RUNTIME_IMAGE"]
            self.assertEqual(image, PIN)


class PlanRuntimeImageTest(unittest.TestCase):
    def test_pinned_runtime_image_replaces_stock_image(self):
        plan = sandbox.plan("auto", preferred="bubblewrap",
                            runtime_image=PIN, probe=False)
        self.assertEqual(plan.runtime_image, PIN)
        self.assertIn("runtime_image", plan.as_dict())
        self.assertIn("image_digest", plan.as_dict())

    def test_no_runtime_image_keeps_default(self):
        plan = sandbox.plan("auto", preferred="bubblewrap", probe=False)
        self.assertEqual(plan.runtime_image, "")
        self.assertEqual(plan.image, sandbox.DEFAULT_IMAGE)


if __name__ == "__main__":
    unittest.main()
