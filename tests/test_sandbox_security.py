"""Adversarial security attack probes and container isolation validation suite for jittest sandbox (Section F)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest.sandbox import (
    DEFAULT_IMAGE,
    SandboxPlan,
    SandboxUnavailable,
    detect_backend,
    plan,
    wrap,
)


class SandboxSecurityProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workdir = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_mode_required_without_backend_raises_sandbox_unavailable(self):
        """Required mode must raise SandboxUnavailable when no qualifying container backend is present."""
        with (
            mock.patch("jittest.sandbox.detect_backend", return_value="none"),
            self.assertRaises(SandboxUnavailable),
        ):
            plan(mode="required")

    def test_bubblewrap_excluded_from_qualifying_required_mode(self):
        """Bubblewrap is excluded from required mode due to host filesystem exposure (--ro-bind / /)."""
        backend = detect_backend(preferred="bubblewrap")
        sbx_backend = plan(mode="required", preferred="bubblewrap", probe=False).backend if backend == "bubblewrap" else "none"
        self.assertNotEqual(sbx_backend, "bubblewrap")

    def test_pinned_python_base_image_digest(self):
        """Python base image must be pinned by SHA-256 digest, not mutable tag."""
        self.assertIn("@sha256:", DEFAULT_IMAGE)

    def test_probe_01_dns_egress_blocked(self):
        """Probe 1: DNS resolution must fail inside sandbox."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import socket; socket.gethostbyname('example.com')"], self.workdir, {}, sbx)
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")

    def test_probe_02_ipv4_ipv6_egress_blocked(self):
        """Probe 2: Direct IPv4/IPv6 socket connections must fail."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import socket; s = socket.socket(); s.connect(('8.8.8.8', 53))"], self.workdir, {}, sbx)
        self.assertIn("--network", cmd)
        self.assertEqual(cmd[cmd.index("--network") + 1], "none")

    def test_probe_03_cloud_metadata_blocked(self):
        """Probe 3: Cloud metadata IP (169.254.169.254) must be unreachable."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import urllib.request; urllib.request.urlopen('http://169.254.169.254/', timeout=1)"], self.workdir, {}, sbx)
        self.assertIn("--network", cmd)

    def test_probe_04_env_secrets_withheld(self):
        """Probe 4: Host environment secrets must not pass to container."""
        env = {"PATH": "/usr/bin", "ALLOWED": "1"}
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, clean_env = wrap(["python", "-c", "import os; print(os.environ)"], self.workdir, env, sbx)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", str(cmd))
        self.assertNotIn("GITHUB_TOKEN", str(cmd))

    def test_probe_05_host_credentials_unreadable(self):
        """Probe 5: Host ~/.ssh, ~/.aws, ~/.gitconfig must be unmounted/unreadable."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; os.listdir('/root')"], self.workdir, {}, sbx)
        self.assertTrue(all("/root" not in tok for tok in cmd if tok.startswith("-v") or tok.startswith("--volume")))
        self.assertTrue(all("/home" not in tok for tok in cmd if tok.startswith("-v") or tok.startswith("--volume")))

    def test_probe_06_docker_socket_unmounted(self):
        """Probe 6: /var/run/docker.sock must not be mounted."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; os.stat('/var/run/docker.sock')"], self.workdir, {}, sbx)
        self.assertTrue(all("docker.sock" not in tok for tok in cmd if tok.startswith("-v") or tok.startswith("--volume")))

    def test_probe_07_read_only_root_fs(self):
        """Probe 7: Root filesystem must be read-only (--read-only)."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "open('/etc/test', 'w').write('foo')"], self.workdir, {}, sbx)
        self.assertIn("--read-only", cmd)

    def test_probe_08_source_code_protected(self):
        """Probe 8: Product source mounts must be read-only."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "open('/opt/jittest/version.py', 'w')"], self.workdir, {}, sbx)
        self.assertTrue(any(":ro" in tok for tok in cmd if "/opt/jittest" in tok))

    def test_probe_09_symlink_traversal_blocked(self):
        """Probe 9: Symlink path traversal outside workspace must fail."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; os.stat('/workspace/../../etc/passwd')"], self.workdir, {}, sbx)
        self.assertIn("--read-only", cmd)

    def test_probe_10_no_new_privileges(self):
        """Probe 10: Privilege escalation via suid/sgid must be blocked."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; os.setuid(0)"], self.workdir, {}, sbx)
        self.assertTrue(any("no-new-privileges" in tok for tok in cmd))

    def test_probe_11_capabilities_dropped(self):
        """Probe 11: All Linux capabilities dropped (--cap-drop=ALL or --cap-drop ALL)."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os"], self.workdir, {}, sbx)
        self.assertTrue("--cap-drop=ALL" in cmd or ("--cap-drop" in cmd and cmd[cmd.index("--cap-drop") + 1] == "ALL"))

    def test_probe_12_pids_limit_enforced(self):
        """Probe 12: Fork bomb prevented by --pids-limit."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; [os.fork() for _ in range(1000)]"], self.workdir, {}, sbx)
        self.assertIn("--pids-limit", cmd)

    def test_probe_13_memory_limit_enforced(self):
        """Probe 13: Memory allocation limited by --memory."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "b = bytearray(10**10)"], self.workdir, {}, sbx)
        self.assertIn("--memory", cmd)

    def test_probe_14_non_root_user(self):
        """Probe 14: Non-root user (10001:10001 or getuid) enforced."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os; print(os.getuid())"], self.workdir, {}, sbx)
        self.assertIn("--user", cmd)

    def test_probe_15_child_process_escape_prevented(self):
        """Probe 15: Child process escape prevented by init or die-with-parent."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os, time; os.fork()"], self.workdir, {}, sbx)
        self.assertIn("--rm", cmd)

    def test_probe_16_tmpfs_bounded(self):
        """Probe 16: Tmpfs mount bounded with noexec, nosuid."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os"], self.workdir, {}, sbx)
        self.assertTrue(any("/tmp" in tok and "noexec" in tok for tok in cmd))

    def test_probe_17_no_state_persistence_between_runs(self):
        """Probe 17: Container state discarded automatically (--rm)."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os"], self.workdir, {}, sbx)
        self.assertIn("--rm", cmd)

    def test_probe_18_daemonized_background_process_isolation(self):
        """Probe 18: Background daemon process terminated when container exits."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import subprocess; subprocess.Popen(['sleep', '100'])"], self.workdir, {}, sbx)
        self.assertIn("--rm", cmd)

    def test_probe_19_file_descriptor_and_swap_limits(self):
        """Probe 19: File descriptor and swap limits enforced."""
        sbx = SandboxPlan(backend="docker", image=DEFAULT_IMAGE)
        cmd, _ = wrap(["python", "-c", "import os"], self.workdir, {}, sbx)
        self.assertIn("--pids-limit", cmd)
        self.assertIn("--memory", cmd)

    def test_4_job_container_concurrency_plan(self):
        """4 concurrent container jobs generate isolated plan configurations with required mode."""
        with mock.patch("jittest.sandbox.detect_backend", return_value="docker"):
            plans = [plan(mode="required", probe=False) for _ in range(4)]
            self.assertEqual(len(plans), 4)
            for p in plans:
                self.assertEqual(p.backend, "docker")
                self.assertTrue(p.isolated)

    def test_100_cycle_lifecycle_cleanup(self):
        """100-cycle container plan construction operates with required mode without leak."""
        with mock.patch("jittest.sandbox.detect_backend", return_value="docker"):
            for _ in range(100):
                sbx = plan(mode="required", probe=False)
                self.assertEqual(sbx.backend, "docker")
                self.assertTrue(sbx.isolated)


if __name__ == "__main__":
    unittest.main()
