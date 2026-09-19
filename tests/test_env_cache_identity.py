"""Environment provisioning identity and budget invariants.

Regression guards for the Windows/3.11 CI failure on PR #224: base and head
with byte-identical requirements built two venvs, and per-step installer caps
summed past the caller's deadline so the failure surfaced as an untyped kill.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from jittest import env as env_mod
from jittest.env import EnvSetupError, _ProvisionDeadline, env_cache_identity


class EnvCacheIdentityTests(unittest.TestCase):
    def _key(self, **kw: object) -> str:
        base: dict[str, object] = dict(
            repo=Path("/tmp/repo"), commit_sha="a" * 40, target_py="3.11",
            cutoff="2026-01-01T00:00:00Z", lockfile_hash="f" * 64,
            needs_editable=False, uv_present=False,
        )
        base.update(kw)
        return env_cache_identity(**base)  # type: ignore[arg-type]

    def test_identical_requirements_share_one_env_across_commits(self) -> None:
        base = self._key(commit_sha="a" * 40, cutoff="2026-01-01T00:00:00Z")
        head = self._key(commit_sha="b" * 40, cutoff="2026-02-02T00:00:00Z")
        self.assertEqual(base, head)

    def test_manifest_bytes_change_identity(self) -> None:
        self.assertNotEqual(self._key(lockfile_hash="1" * 64), self._key(lockfile_hash="2" * 64))

    def test_interpreter_line_changes_identity(self) -> None:
        self.assertNotEqual(self._key(target_py="3.11"), self._key(target_py="3.12"))

    def test_cutoff_only_matters_when_a_resolver_applies_it(self) -> None:
        # pip fallback ignores --exclude-newer: cutoff must not fragment the cache
        self.assertEqual(self._key(cutoff="2026-01-01T00:00:00Z"), self._key(cutoff=""))
        # uv applies it: era-correct resolution must stay distinct
        self.assertNotEqual(
            self._key(uv_present=True, cutoff="2026-01-01T00:00:00Z"),
            self._key(uv_present=True, cutoff="2026-02-02T00:00:00Z"),
        )

    def test_editable_projects_stay_pinned_per_repo_and_commit(self) -> None:
        a = self._key(needs_editable=True, commit_sha="a" * 40)
        b = self._key(needs_editable=True, commit_sha="b" * 40)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, self._key(needs_editable=True, repo=Path("/tmp/other")))

    def test_identity_is_short_hex_and_deterministic(self) -> None:
        k = self._key()
        self.assertEqual(k, self._key())
        self.assertEqual(len(k), 16)
        int(k, 16)


class ProvisionDeadlineTests(unittest.TestCase):
    def test_bounded_never_exceeds_request_or_remaining(self) -> None:
        now = [100.0]
        d = _ProvisionDeadline(50.0, clock=lambda: now[0])
        self.assertEqual(d.bounded(30), 30.0)
        now[0] = 130.0
        self.assertEqual(d.bounded(90), 20.0)

    def test_exhausted_budget_is_a_typed_refusal_not_a_spawn(self) -> None:
        now = [0.0]
        d = _ProvisionDeadline(10.0, clock=lambda: now[0])
        now[0] = 10.0
        with self.assertRaises(EnvSetupError) as ctx:
            d.bounded(60, "pytest")
        self.assertIn("env_build_timeout", str(ctx.exception))
        self.assertIn("pytest", str(ctx.exception))

    def test_floor_of_one_second_avoids_zero_timeouts(self) -> None:
        now = [0.0]
        d = _ProvisionDeadline(10.0, clock=lambda: now[0])
        now[0] = 9.9995
        self.assertEqual(d.bounded(60), 1.0)

    def test_budget_is_env_tunable_and_finite(self) -> None:
        self.assertGreater(env_mod.PROVISION_BUDGET_S, 0)
        self.assertLess(env_mod.PROVISION_BUDGET_S, 3600)


if __name__ == "__main__":
    unittest.main()
