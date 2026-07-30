"""Defects 72 and 73, both found by this project's own CI rather than by
reading the code.

The isolation work landed with nine test jobs green on macOS and Windows and
two red on Linux. That split was the whole message: the Linux runners are the
only ones in the matrix with a container engine installed, so they were the
only ones that actually took the container path. Every other job had been
exercising the fallback and reporting it as a pass.

Defect 72 - the candidate could not import the runner inside the container.
    A candidate is executed by ``jittest._minirunner``, so the jittest package
    root is on the candidate's PYTHONPATH. That directory lives outside the
    checkout, nothing mounted it, and PYTHONPATH was rewritten only for paths
    under the checkout. The entry survived pointing at a host path that does
    not exist in the image. Result: every candidate failed to start, and a
    candidate that fails to start on head is one half of "catching".

Defect 73 - auto mode would pull an image mid-run.
    ``docker run`` fetches a missing image. In ``auto`` - the default - that is
    an unannounced download inside somebody's pull request, on a runner that
    may have no registry access, and the failure arrives disguised as candidate
    errors. Auto now isolates with what is already present; ``required`` is
    where the user has asked for the image and accepts the pull.

Both are the same mistake in different clothes, and it is the mistake this
repository keeps making: an infrastructure failure that is indistinguishable
from a result about the code under test.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from jittest import sandbox as S


class PackageRootReachesTheContainer(unittest.TestCase):
    """Defect 72."""

    def setUp(self):
        self.plan = S.SandboxPlan(backend="docker", image="python:3.13-slim")
        # Deliberately not the current directory. When jittest is dogfooded on
        # its own checkout the package root IS inside the workdir, and then
        # /workspace/src is the right answer - a real case, but not this one.
        self.workdir = Path(tempfile.mkdtemp(prefix="jittest-wrap-")).resolve()
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)

    def argv(self, env=None):
        env = env or {"PYTHONPATH": os.pathsep.join(
            [str(self.workdir), str(S._PACKAGE_ROOT)])}
        out, _ = S.wrap(["python", "-m", "jittest._minirunner"],
                        self.workdir, env, self.plan)
        return out

    def test_package_root_is_mounted_read_only(self):
        argv = self.argv()
        mount = f"{S._PACKAGE_ROOT}:{S._PACKAGE_MOUNT}:ro"
        self.assertIn(mount, argv,
                      "without this bind the candidate cannot import the "
                      "runner that is supposed to execute it")

    def test_package_root_is_not_writable_by_the_candidate(self):
        """The thing being judged must not be able to edit the judge."""
        binds = [argv for argv in self.argv() if str(S._PACKAGE_ROOT) in argv]
        self.assertTrue(binds)
        for bind in binds:
            self.assertTrue(bind.endswith(":ro"), bind)

    def test_pythonpath_points_at_the_mount_not_the_host(self):
        argv = self.argv()
        pythonpath = [a for a in argv if a.startswith("PYTHONPATH=")]
        self.assertEqual(len(pythonpath), 1)
        value = pythonpath[0].split("=", 1)[1]
        self.assertIn(S._PACKAGE_MOUNT, value)
        self.assertIn("/workspace", value)
        self.assertNotIn(str(S._PACKAGE_ROOT), value)

    def test_host_only_entries_are_dropped_rather_than_carried(self):
        """A path that does not exist in the image is not a harmless leftover:
        it silently changes what the candidate can import."""
        env = {"PYTHONPATH": os.pathsep.join(
            [str(self.workdir), "/opt/hostdeps/site-packages"])}
        value = ":".join(S._container_pythonpath(env["PYTHONPATH"], self.workdir))
        self.assertEqual(value, "/workspace")

    def test_empty_segments_do_not_become_the_current_directory(self):
        """An empty PYTHONPATH entry means 'cwd' to Python, which inside the
        container is a different directory than it was on the host."""
        self.assertEqual(
            S._container_pythonpath(f"{os.pathsep}{os.pathsep}", self.workdir), [])


class AutoNeverPulls(unittest.TestCase):
    """Defect 73."""

    def setUp(self):
        self.detect = S.detect_backend
        self.present = S._image_present
        self.probe = S.probe_backend

    def tearDown(self):
        S.detect_backend = self.detect
        S._image_present = self.present
        S.probe_backend = self.probe

    def test_auto_falls_back_when_the_image_is_absent(self):
        S.detect_backend = lambda preferred="": "docker" if not preferred else "none"
        S._image_present = lambda backend, image: False
        p = S.plan("auto", probe=False)
        self.assertEqual(p.backend, "none")
        self.assertFalse(p.isolated)
        self.assertTrue(any("pull" in n for n in p.notes),
                        "the user must be told how to get isolation back")

    def test_auto_prefers_bubblewrap_over_giving_up(self):
        """A namespace sandbox needs no image at all, so an absent image is no
        reason to run unconfined when bwrap is right there."""
        S.detect_backend = (
            lambda preferred="": "bubblewrap" if preferred == "bubblewrap" else "docker")
        S._image_present = lambda backend, image: False
        p = S.plan("auto", probe=False)
        self.assertEqual(p.backend, "bubblewrap")
        self.assertTrue(p.network_denied)

    def test_auto_uses_the_container_when_the_image_is_already_there(self):
        S.detect_backend = lambda preferred="": "docker"
        S._image_present = lambda backend, image: True
        p = S.plan("auto", probe=False)
        self.assertEqual(p.backend, "docker")

    def test_required_still_accepts_the_pull(self):
        """'required' is an explicit request for isolation. Refusing to fetch
        the image there would turn a working configuration into an error."""
        S.detect_backend = lambda preferred="": "docker"
        S._image_present = lambda backend, image: False
        S.probe_backend = lambda backend, image: (True, "")
        p = S.plan("required", probe=True)
        self.assertEqual(p.backend, "docker")

    def test_the_fallback_is_recorded_not_merely_implied(self):
        S.detect_backend = lambda preferred="": "docker" if not preferred else "none"
        S._image_present = lambda backend, image: False
        p = S.plan("auto", probe=False)
        self.assertTrue(p.notes)
        joined = " ".join(p.notes)
        self.assertIn("unconfined", joined)


class TheSuiteDoesNotDependOnTheHost(unittest.TestCase):
    """The reason two Linux jobs failed while seven others passed.

    A test whose result depends on whether the machine running it happens to
    have a container engine is not a test, it is a coin flip with a changelog
    entry. Anything asserting isolation behaviour stubs the detection.
    """

    def test_off_is_deterministic_everywhere(self):
        for _ in range(3):
            p = S.plan("off", probe=False)
            self.assertEqual(p.backend, "none")
            self.assertFalse(p.network_denied)

    def test_image_presence_check_never_runs_the_image(self):
        """`image inspect` reads the local store. `run` would fetch it."""
        seen = {}

        def fake_usable(binary, args):
            seen["args"] = args
            return True

        original = S._usable
        S._usable = fake_usable
        try:
            self.assertTrue(S._image_present("docker", "python:3.13-slim"))
        finally:
            S._usable = original
        self.assertEqual(seen["args"][:2], ["image", "inspect"])
        self.assertNotIn("run", seen["args"])


if __name__ == "__main__":
    unittest.main()
