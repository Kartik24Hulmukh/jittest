"""Option C trusted-image inventory — regression tests for issue #198 item 2.

The inventory must never be an empty lie: when a maintainer pins a runtime
image by digest, provisioning reports exact ``name==version`` pins collected
from inside the image, and every failure to obtain them is a typed refusal.
These tests run without a container engine; the engine boundary is faked.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest import env as E  # noqa: E402
from jittest.sandbox import SandboxPlan  # noqa: E402
from jittest.verify import VerifyRefusalError  # noqa: E402

PIN = "ghcr.io/example/runtime@sha256:" + "a" * 64


class _OkProc:
    returncode = 0
    stdout = '[{"name": "Flask", "version": "3.1.0"}, {"name": "requests", "version": "2.32.4"}, {"name": "", "version": "1"}]'
    stderr = ""


class TestOptionCInventory(unittest.TestCase):
    def _plan(self, backend="docker", digest="sha256:" + "c" * 64):
        return SandboxPlan(backend=backend, runtime_image=PIN, image_digest=digest)

    def _manifest(self, deps):
        m = mock.Mock()
        m.ambiguous = False
        m.symlink_escapes = []
        m.reasons = []
        m.declared_dependencies = deps
        return m

    def test_inventory_is_built_from_image_probe(self):
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest(["flask"])), \
             mock.patch.object(E.subprocess, "run", return_value=_OkProc()) as run:
            info = E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan())
        self.assertEqual(
            info["resolved_versions"], ["Flask==3.1.0", "requests==2.32.4"],
            "inventory must carry exact pins, not an empty list",
        )
        self.assertEqual(info["provisioning"], "option_c_trusted_image")
        cmd = run.call_args.args[0]
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none", "inventory probe must not touch the network")

    def test_empty_inventory_now_refuses(self):
        class _Empty(_OkProc):
            stdout = "[]"
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest(["flask"])), \
             mock.patch.object(E.subprocess, "run", return_value=_Empty()), \
             self.assertRaises(VerifyRefusalError) as ctx:
            E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan())
        self.assertEqual(ctx.exception.reason.code, "image_inventory_empty")

    def test_probe_failure_refuses_fail_closed(self):
        class _Bad(_OkProc):
            returncode = 1
            stdout = ""
            stderr = "unable to start container"
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest(["flask"])), \
             mock.patch.object(E.subprocess, "run", return_value=_Bad()), \
             self.assertRaises(VerifyRefusalError) as ctx:
            E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan())
        self.assertEqual(ctx.exception.reason.code, "image_inventory_failed")

    def test_malformed_json_refuses(self):
        class _Junk(_OkProc):
            stdout = "not json at all"
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest(["flask"])), \
             mock.patch.object(E.subprocess, "run", return_value=_Junk()), \
             self.assertRaises(VerifyRefusalError) as ctx:
            E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan())
        self.assertEqual(ctx.exception.reason.code, "image_inventory_malformed")

    def test_refusal_is_typed_at_provision_phase(self):
        class _Bad(_OkProc):
            returncode = 1
            stdout = ""
            stderr = "boom"
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest(["flask"])), \
             mock.patch.object(E.subprocess, "run", return_value=_Bad()), \
             self.assertRaises(VerifyRefusalError) as ctx:
            E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan())
        self.assertEqual(ctx.exception.reason.phase, "provision")
        self.assertNotIn("token", str(ctx.exception.reason.details).lower())

    def test_non_container_backends_do_not_probe(self):
        with mock.patch.object(E.discovery, "discover_manifest", return_value=self._manifest([])), \
             mock.patch.object(E.subprocess, "run") as run:
            info = E.provision_environment("/tmp/wt", "a" * 40, "/tmp/repo", sbx_plan=self._plan(backend="bubblewrap"))
        run.assert_not_called()
        self.assertEqual(info["resolved_versions"], [])


if __name__ == "__main__":
    unittest.main()
