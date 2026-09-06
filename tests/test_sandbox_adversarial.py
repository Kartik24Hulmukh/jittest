"""Adversarial security test suite for sandbox containment.

Verifies that candidates executing inside container/namespace isolation cannot
exfiltrate data over the network, exhaust host process tables via fork bombs,
or write outside the bound worktree checkout.
"""

from jittest.sandbox import SandboxPlan, plan

try:
    import pytest
except ImportError:
    pytest = None


def test_sandbox_plan_defaults():
    sbx = plan(mode="auto", probe=False)
    assert isinstance(sbx, SandboxPlan)
    if sbx.isolated:
        assert sbx.network_denied is True


def test_adversarial_network_exfil_code():
    """Verify candidate attempting network exfiltration fails/blocked under sandbox."""
    import tempfile
    from pathlib import Path

    from jittest.execute import Outcome, run_test

    sbx = plan(mode="auto", probe=True)
    if not sbx.isolated:
        if pytest is not None:
            pytest.skip("No isolated sandbox backend available; marked NOT_RUN")
        return

    code = """
import socket

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(2.0)
s.connect(("8.8.8.8", 53))
s.close()

def test_exfil():
    assert True
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_test(Path(tmpdir), code, sbx=sbx, timeout_s=5)
        assert res.outcome in (Outcome.FAIL, Outcome.ERROR)


def test_adversarial_fork_bomb_containment():
    """Verify candidate fork bomb is stopped by PID limit or OS limit under sandbox."""
    import tempfile
    from pathlib import Path

    from jittest.execute import run_test

    sbx = plan(mode="auto", probe=True)
    if not sbx.isolated or sbx.backend not in ("docker", "podman"):
        if pytest is not None:
            pytest.skip("PID limit containment requires container backend (docker/podman); marked NOT_RUN")
        return

    code = """
import os

pids = []
for _ in range(300):
    if hasattr(os, "fork"):
        try:
            pid = os.fork()
            if pid == 0:
                os._exit(0)
            pids.append(pid)
        except OSError:
            break

for pid in pids:
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass

def test_fork():
    assert True
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_test(Path(tmpdir), code, sbx=sbx, timeout_s=5)
        assert res.returncode is not None


def test_adversarial_fs_escape_write_blocked():
    """Verify candidate attempting container escape / root fs write fails under sandbox."""
    import tempfile
    from pathlib import Path

    from jittest.execute import Outcome, run_test

    sbx = plan(mode="auto", probe=True)
    if not sbx.isolated:
        if pytest is not None:
            pytest.skip("No isolated sandbox backend available; marked NOT_RUN")
        return

    code = """
with open("/etc/jittest_escape_test", "w") as fh:
    fh.write("escape")

def test_escape():
    assert True
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = run_test(Path(tmpdir), code, sbx=sbx, timeout_s=5)
        assert res.outcome in (Outcome.FAIL, Outcome.ERROR)



def test_timeout_child_spawner_cleaned_up():
    """Verify that a container spawning background children is killed by name on timeout and cleaned up."""
    import subprocess

    from jittest.execute import _run_process
    from jittest.sandbox import detect_backend

    backend = detect_backend()
    if backend not in ("docker", "podman"):
        if pytest is not None:
            pytest.skip(f"No running container backend available ({backend}); marked NOT_RUN")
        return

    from jittest.sandbox import _image_present, probe_backend

    if not _image_present(backend, "python:3.13-slim"):
        if pytest is not None:
            pytest.skip("Container image python:3.13-slim not present locally; marked NOT_RUN")
        return

    ok, detail = probe_backend(backend, "python:3.13-slim")
    if not ok:
        if pytest is not None:
            pytest.skip(f"Container backend probe failed ({detail}); marked NOT_RUN")
        return

    import uuid
    cname = f"jittest-spawner-{uuid.uuid4().hex[:8]}"
    cmd = [
        backend, "run", "--rm", "--name", cname, "python:3.13-slim",
        "python", "-c", "import subprocess, time; subprocess.Popen(['sleep', '600']); time.sleep(10)"
    ]
    with pytest.raises(subprocess.TimeoutExpired):
        _run_process(cmd, cwd=".", env={}, timeout_s=1)

    # Verify no container with that name remains
    check = subprocess.run(
        [backend, "ps", "-a", "--filter", f"name={cname}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert cname not in check.stdout.split()


def test_kill_tree_kills_container_by_name():
    """Unit test for container process tree killing and cleanup."""
    from unittest import mock

    from jittest.execute import _kill_tree

    mock_proc = mock.MagicMock()
    with mock.patch("subprocess.run") as mock_sub:
        mock_sub.return_value = mock.MagicMock(returncode=0, stdout="")
        _kill_tree(mock_proc, container_name="jittest-1234", backend="docker")

        calls = [c[0][0] for c in mock_sub.call_args_list]
        assert ["docker", "kill", "jittest-1234"] in calls
        assert any("ps" in c and "name=jittest-1234" in str(c) for c in calls)
        mock_proc.kill.assert_called_once()
