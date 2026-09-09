import unittest
from unittest import mock
import subprocess
from pathlib import Path
import sys

from jittest.option_b import (
    make_phase1_fetch_plan,
    make_phase2_install_plan,
    run_option_b_provisioning,
    OptionBRefusalError
)
from jittest.sandbox import SandboxPlan

class TestOptionB(unittest.TestCase):
    def test_make_phase1_fetch_plan(self):
        plan = make_phase1_fetch_plan("req.txt", "/tmp/wh", backend="docker")
        
        # Invariants:
        # 1. No candidate mount (only wheelhouse dir is mounted)
        # 2. Must contain --only-binary :all:
        # 3. Uses docker / podman run
        
        self.assertIn("docker", plan)
        self.assertIn("run", plan)
        self.assertIn("-v", plan)
        
        # Only the wheelhouse mount should be present
        wh_mount = "/tmp/wh:/wheelhouse"
        # Find all mount options
        v_indices = [i for i, val in enumerate(plan) if val == "-v"]
        self.assertEqual(len(v_indices), 1)
        self.assertTrue(plan[v_indices[0]+1].endswith(":/wheelhouse"))
        
        # Enforces binary wheels only
        self.assertIn("--only-binary", plan)
        self.assertIn(":all:", plan)

    def test_make_phase2_install_plan(self):
        plan = make_phase2_install_plan("/tmp/wh", "/tmp/candidate", backend="docker")
        
        # Invariants:
        # 1. Network severed: --network none
        # 2. Wheelhouse and worktree mounted read-only
        # 3. System root read-only: --read-only
        
        self.assertIn("--network", plan)
        self.assertIn("none", plan)
        self.assertIn("--read-only", plan)
        
        # Both mounts must be ro
        v_indices = [i for i, val in enumerate(plan) if val == "-v"]
        self.assertEqual(len(v_indices), 2)
        mounts = [plan[i+1] for i in v_indices]
        self.assertTrue(any(m.endswith(":/wheelhouse:ro") for m in mounts))
        self.assertTrue(any(m.endswith(":/workspace:ro") for m in mounts))

    @mock.patch("subprocess.run")
    def test_run_option_b_provisioning_success(self, mock_run):
        # Stub subprocess.run to return success
        mock_run.return_value = mock.Mock(returncode=0, stdout="success", stderr="")
        
        sbx = SandboxPlan(backend="docker")
        res = run_option_b_provisioning(
            worktree_dir=Path("/tmp/worktree"),
            declared_dependencies=["flask", "requests"],
            sbx_plan=sbx
        )
        
        self.assertEqual(res["provisioning"], "option_b_two_phase")
        self.assertTrue(res["has_project_dependencies"])
        self.assertIn("wheelhouse_dir", res)

    @mock.patch("subprocess.run")
    def test_run_option_b_provisioning_sdist_refusal(self, mock_run):
        # Stub subprocess.run to fail with sdist compiler / build backend error
        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="pip download failed with sdist build or only-binary error"
        )
        
        sbx = SandboxPlan(backend="docker")
        with self.assertRaises(OptionBRefusalError) as ctx:
            run_option_b_provisioning(
                worktree_dir=Path("/tmp/worktree"),
                declared_dependencies=["flask", "requests"],
                sbx_plan=sbx
            )
        self.assertEqual(ctx.exception.code, "unsupported_packaging")

    @mock.patch("subprocess.run")
    def test_run_option_b_provisioning_network_error(self, mock_run):
        # Stub subprocess.run to fail with connection/network error
        mock_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="Connection timed out or could not reach PyPI"
        )
        
        sbx = SandboxPlan(backend="docker")
        with self.assertRaises(OptionBRefusalError) as ctx:
            run_option_b_provisioning(
                worktree_dir=Path("/tmp/worktree"),
                declared_dependencies=["flask", "requests"],
                sbx_plan=sbx
            )
        self.assertEqual(ctx.exception.code, "fetch_network_error")

    @mock.patch("subprocess.run")
    def test_run_option_b_provisioning_timeout(self, mock_run):
        # Stub subprocess.run to raise TimeoutExpired
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker"], timeout=180)
        
        sbx = SandboxPlan(backend="docker")
        with self.assertRaises(OptionBRefusalError) as ctx:
            run_option_b_provisioning(
                worktree_dir=Path("/tmp/worktree"),
                declared_dependencies=["flask", "requests"],
                sbx_plan=sbx
            )
        self.assertEqual(ctx.exception.code, "timeout")

if __name__ == '__main__':
    unittest.main()
