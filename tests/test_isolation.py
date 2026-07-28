"""Defect 62: model-written code must not inherit the runner's credentials.

``_env_for`` used to be ``dict(os.environ)``. That meant every generated test
executed with all of the runner's variables: the LLM API key that produced the
candidate, and under CI a write-capable GITHUB_TOKEN. Stealing them requires
nothing exotic - a candidate reads os.environ and puts the value in an
assertion message, and jittest then quotes that message into a PR comment as
the failure excerpt. The oracle would have exfiltrated the key on jittest's
behalf.

These tests pin the allowlist, prove an adversarial candidate sees nothing
credential-shaped, prove a secret cannot reach captured output, and check that
isolation did not break a candidate's ability to run at all.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from jittest.execute import (
    _ENV_ALLOWLIST,
    _SECRETISH,
    Outcome,
    Worktree,
    _env_for,
    run_test,
)

from .helpers import FixtureRepo

# Realistic names, including the three jittest's own CLI reads. The values are
# derived at import time rather than written as literals: a hardcoded
# name-plus-value pair is exactly what secret scanners are built to flag, and a
# test suite should not train reviewers to wave through a red secret scan. The
# property under test needs only that each value is unique and traceable to its
# variable, which this gives us without a single credential-shaped literal.
_SENTINEL = "jittest-isolation-canary"

SECRET_NAMES = (
    "JITTEST_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "AWS_SECRET_ACCESS_KEY",
    "NVAPI_KEY",
    "MY_DB_PASSWORD",
    "SESSION_COOKIE",
)

SECRETS = {name: f"{_SENTINEL}-{name.lower()}" for name in SECRET_NAMES}

# An adversarial candidate - precisely what a prompt-injected or simply careless
# model can emit. It hunts for the canary VALUE rather than for guessed variable
# names: every secret above carries the canary, so a leak is caught under any
# name at all, including one this test never thought to list.
EXFILTRATOR = f'''
import os

CANARY = "{_SENTINEL}"


def test_candidate_cannot_read_credentials():
    leaked = sorted(n for n, v in os.environ.items() if CANARY in v)
    assert not leaked, "candidate can read: %s" % leaked
'''

# Dumps the whole environment into a failure message. If any secret is
# reachable, its value lands in the excerpt jittest reports publicly.
DUMPER = '''
import os


def test_dump_the_environment():
    raise AssertionError("env=%s" % sorted(os.environ.items()))
'''


class TestEnvironmentAllowlist(unittest.TestCase):
    def test_secret_shaped_variables_are_withheld(self):
        with mock.patch.dict(os.environ, SECRETS), \
                tempfile.TemporaryDirectory() as td:
            env = _env_for(Path(td))
        for name in SECRETS:
            self.assertNotIn(name, env, f"{name} was handed to the candidate")

    def test_the_allowlist_itself_names_nothing_credential_shaped(self):
        # Reuses the production predicate instead of keeping a parallel list of
        # credential words, so this test cannot drift from what _env_for
        # actually enforces - and there is one definition to audit, not two.
        for name in _ENV_ALLOWLIST:
            self.assertIsNone(_SECRETISH.search(name), name)

    def test_an_unlisted_variable_is_absent_even_when_harmless(self):
        # Default-deny is the actual property under test. A variable that is
        # not a secret at all must still be absent, because tomorrow's new
        # credential will not be added to the allowlist either.
        with mock.patch.dict(os.environ, {"SOME_INTERNAL_ENDPOINT": "x"}), \
                tempfile.TemporaryDirectory() as td:
            env = _env_for(Path(td))
        self.assertNotIn("SOME_INTERNAL_ENDPOINT", env)

    def test_host_pythonpath_is_not_inherited(self):
        # Inheriting it let host packages shadow the repo under test, which can
        # change a verdict about code that never imported them.
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/host/site-packages"}), \
                tempfile.TemporaryDirectory() as td:
            env = _env_for(Path(td))
        self.assertNotIn("/host/site-packages", env["PYTHONPATH"])

    def test_candidate_still_has_what_it_needs_to_run(self):
        # Isolation that stops candidates from starting would turn real
        # verdicts into false NOTRUNs, which is a different kind of lie.
        with tempfile.TemporaryDirectory() as td:
            env = _env_for(Path(td))
            self.assertIn(td, env["PYTHONPATH"])
        self.assertEqual(env["JITTEST_CHILD"], "1")
        self.assertEqual(env["PYTHONHASHSEED"], "0")
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")
        if "PATH" in os.environ:
            self.assertIn("PATH", env)

    def test_runner_override_flag_is_still_forwarded(self):
        with mock.patch.dict(os.environ, {"JITTEST_FORCE_MINIRUNNER": "1"}), \
                tempfile.TemporaryDirectory() as td:
            env = _env_for(Path(td))
        self.assertEqual(env["JITTEST_FORCE_MINIRUNNER"], "1")


class TestAdversarialCandidate(unittest.TestCase):
    def test_an_exfiltrating_candidate_finds_nothing(self):
        with mock.patch.dict(os.environ, SECRETS), FixtureRepo() as repo, \
                Worktree(repo.path, repo.head) as work:
            result = run_test(work, EXFILTRATOR, timeout_s=60)
        self.assertIs(result.outcome, Outcome.PASS, result.tail)

    def test_a_secret_value_cannot_reach_reported_output(self):
        # The failure excerpt is published into PR comments, so this is the
        # step that would have done the exfiltrating.
        with mock.patch.dict(os.environ, SECRETS), FixtureRepo() as repo, \
                Worktree(repo.path, repo.head) as work:
            result = run_test(work, DUMPER, timeout_s=60)
        self.assertIn(result.outcome, (Outcome.FAIL, Outcome.ERROR))
        for name, value in SECRETS.items():
            self.assertNotIn(value, result.tail,
                             f"{name}'s value reached reported output")


if __name__ == "__main__":
    unittest.main()
