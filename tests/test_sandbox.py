"""Isolation is the last production-readiness blocker, so it gets tests that
assume it will be wrong rather than tests that confirm it is right.

The threat is specific and it is not hypothetical. jittest reads a pull
request's title and body, puts them into a generator prompt, and then executes
whatever Python comes back. Everything between the prompt and the execution is
advisory: the safety checker is an AST allowlist, and an AST allowlist is a
filter on the shapes of code an attacker chose to write. Confinement is the
only control here that does not depend on having anticipated the attack.

Two failure modes matter more than the happy path, and both are tested below.

First, silent downgrade. A sandbox that quietly does nothing is worse than no
sandbox, because the run still reports success and the operator still believes
candidates were confined. Every unconfined path must therefore leave a written
note, and "required" must refuse rather than degrade.

Second, manufactured verdicts. A failing test on head that passes on base is
jittest's entire output. If a broken container backend makes every candidate
fail, the backend has become a fact generator rather than a fact recorder.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jittest import sandbox as S  # noqa: E402
from jittest.config import Config, normalise_values  # noqa: E402


class PlanModes(unittest.TestCase):
    def test_off_is_honest_about_what_it_means(self):
        p = S.plan("off", probe=False)
        self.assertFalse(p.isolated)
        self.assertEqual(p.backend, "none")
        # The note is the whole point. A user who turns isolation off should
        # find that decision restated in the report, not buried in a config
        # file they edited three weeks ago.
        self.assertTrue(p.notes, "disabling isolation must be recorded")

    def test_required_refuses_rather_than_degrades(self):
        """Fail closed. This is the branch that makes the mode worth having."""
        original = S.detect_backend
        S.detect_backend = lambda preferred="": "none"
        try:
            with self.assertRaises(S.SandboxUnavailable):
                S.plan("required", probe=False)
        finally:
            S.detect_backend = original

    def test_auto_falls_back_but_says_so(self):
        original = S.detect_backend
        S.detect_backend = lambda preferred="": "none"
        try:
            p = S.plan("auto", probe=False)
        finally:
            S.detect_backend = original
        self.assertFalse(p.isolated)
        self.assertTrue(p.notes)

    def test_unknown_mode_is_not_interpreted_charitably(self):
        """`JITTEST_SANDBOX=on` is a plausible typo for `required`.

        Guessing what the user meant would silently select the weakest
        setting under a name that reads like the strongest one.
        """
        clean, notes = normalise_values({"sandbox_mode": "on"})
        self.assertEqual(clean["sandbox_mode"], "auto")
        self.assertTrue(any("sandbox_mode" in n for n in notes))

    def test_known_modes_survive_normalisation(self):
        for mode in ("auto", "required", "off", "REQUIRED", " off "):
            clean, _ = normalise_values({"sandbox_mode": mode})
            self.assertEqual(clean["sandbox_mode"], mode.strip().lower())

    def test_unknown_backend_is_rejected(self):
        clean, notes = normalise_values({"sandbox_backend": "firejail"})
        self.assertEqual(clean["sandbox_backend"], "")
        self.assertTrue(any("sandbox_backend" in n for n in notes))

    def test_config_defaults_to_auto(self):
        self.assertEqual(Config().sandbox_mode, "auto")


class PlanShape(unittest.TestCase):
    def test_as_dict_is_serialisable_and_complete(self):
        d = S.plan("off", probe=False).as_dict()
        for key in ("backend", "image", "isolated", "network_denied", "notes"):
            self.assertIn(key, d)
        json.loads(json.dumps(d))       # must survive the report round trip

    def test_network_denied_only_claimed_when_isolated(self):
        """An unconfined run has full network access. Reporting otherwise
        would be a false security claim in a machine-readable field."""
        self.assertFalse(S.plan("off", probe=False).network_denied)


class Wrapping(unittest.TestCase):
    def test_wrap_is_a_passthrough_when_unisolated(self):
        """One code path. `run_test` must not branch on the mode itself."""
        p = S.plan("off", probe=False)
        argv = ["python", "test_x.py"]
        env = {"PATH": "/usr/bin"}
        out_argv, out_env = S.wrap(argv, Path("/tmp/wd"), env, p)
        self.assertEqual(out_argv, argv)
        self.assertEqual(out_env, env)

    def test_container_paths_are_rewritten_into_the_mount(self):
        """Host paths leaking into a container argv produce a file-not-found
        that looks exactly like a collection error, which the oracle records
        as NOTRUN on head - quietly discarding a possibly real candidate."""
        wd = Path("/var/work/repo")
        argv = ["/usr/bin/python", str(wd / "test_c.py"),
                f"--junitxml={wd / 'r.xml'}"]
        out = S._container_paths(argv, wd)
        self.assertNotIn(str(wd), " ".join(out[1:]))
        self.assertIn("/workspace/test_c.py", out)
        self.assertTrue(any(a.startswith("--junitxml=/workspace/") for a in out))

    def test_container_argv_denies_network_and_privileges(self):
        p = S.SandboxPlan(backend="docker", image="python:3.13-slim")
        argv, _ = S.wrap(["python", "/wd/test_c.py"], Path("/wd"),
                         {"PATH": "/usr/bin"}, p)
        joined = " ".join(argv)
        self.assertIn("--network none", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("no-new-privileges", joined)
        self.assertIn("--read-only", joined)
        self.assertIn("--pids-limit", joined)
        self.assertIn("--memory", joined)

    def test_container_does_not_forward_the_host_path(self):
        """PATH inside the image is not PATH on the runner; forwarding it
        points the container at binaries that were never mounted."""
        p = S.SandboxPlan(backend="docker")
        argv, _ = S.wrap(["python", "/wd/t.py"], Path("/wd"),
                         {"PATH": "/opt/hostedtoolcache/bin",
                          "JITTEST_CHILD": "1"}, p)
        self.assertNotIn("PATH=/opt/hostedtoolcache/bin", argv)
        self.assertIn("JITTEST_CHILD=1", argv)

    @unittest.skipUnless(hasattr(os, "getuid"), "POSIX only")
    def test_container_runs_as_the_calling_user(self):
        """Root-owned files written into the mounted worktree survive
        `reset_workdir`, and state surviving between candidates is Defect 35."""
        p = S.SandboxPlan(backend="podman")
        argv, _ = S.wrap(["python", "/wd/t.py"], Path("/wd"), {}, p)
        self.assertIn(f"{os.getuid()}:{os.getgid()}", argv)

    def test_bwrap_unshares_the_network(self):
        p = S.SandboxPlan(backend="bubblewrap")
        argv, _ = S.wrap(["python", "/wd/t.py"], Path("/wd"), {}, p)
        self.assertEqual(argv[0], "bwrap")
        self.assertIn("--unshare-all", argv)
        self.assertIn("--die-with-parent", argv)


class BrokenBackend(unittest.TestCase):
    """A backend that cannot start is an absence of a measurement."""

    def test_failed_probe_is_not_an_isolated_plan(self):
        original_detect, original_probe = S.detect_backend, S.probe_backend
        original_present = S._image_present
        # Defect 73 put an image-presence check in front of the probe, so a
        # test about probe failure must state that the image is there. Without
        # this the run falls back before it ever probes, and the test would
        # pass for the wrong reason on a machine with no container engine.
        S._image_present = lambda backend, image: True
        S.detect_backend = lambda preferred="": "docker"
        S.probe_backend = lambda backend, image: (False, "daemon not reachable")
        try:
            p = S.plan("auto", probe=True)
            self.assertFalse(
                p.isolated,
                "a backend whose probe failed must never be used: every "
                "candidate would fail on head and on base, and a reader who "
                "looked only at head would call that a catch")
            self.assertTrue(any("daemon not reachable" in n for n in p.notes))
        finally:
            S.detect_backend, S.probe_backend = original_detect, original_probe
            S._image_present = original_present

    def test_failed_probe_under_required_raises(self):
        original_detect, original_probe = S.detect_backend, S.probe_backend
        original_present = S._image_present
        # Defect 73 put an image-presence check in front of the probe, so a
        # test about probe failure must state that the image is there. Without
        # this the run falls back before it ever probes, and the test would
        # pass for the wrong reason on a machine with no container engine.
        S._image_present = lambda backend, image: True
        S.detect_backend = lambda preferred="": "docker"
        S.probe_backend = lambda backend, image: (False, "image pull failed")
        try:
            with self.assertRaises(S.SandboxUnavailable):
                S.plan("required", probe=True)
        finally:
            S.detect_backend, S.probe_backend = original_detect, original_probe
            S._image_present = original_present


if __name__ == "__main__":
    unittest.main()
