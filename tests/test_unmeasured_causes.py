"""Defect 74: a sandbox advisory must never be recorded as a cause of failure.

Run 30754409055 swept twenty youtube-dl bugs and measured none of them. Every
unmeasured row carried the same recorded error:

    no container or namespace backend found (looked for podman, docker,
    bubblewrap): candidates ran unconfined.

pipeline.run appends that note to report.errors for every bug in any run
without an isolation backend, which is every run on a stock GitHub runner. It
is not why the model was never called - an unconfined candidate still runs.
Reading it as the cause produced a remediation plan whose first item was to
start a Docker daemon, an action that would not have measured one more bug.

Plain unittest with no third-party import, so these run in both ci.yml test
steps including the dependency-free one.
"""
from __future__ import annotations

import inspect
import unittest

from eval.run_bugsinpy import BugResult, evaluate_one, summarize
from eval.unmeasured import NO_CAUSE, is_sandbox_advisory, tally, unmeasured_reason

UNCONFINED = (
    "no container or namespace backend found (looked for podman, docker, "
    "bubblewrap): candidates ran unconfined. Credentials were still withheld "
    "by the environment allowlist, but network egress and filesystem writes "
    "outside the checkout were not blocked."
)
DISABLED = (
    "sandbox disabled by configuration: candidate tests share the filesystem, "
    "network and user account of this runner."
)


class SandboxAdvisoryDetection(unittest.TestCase):
    def test_the_run_30754409055_string_is_recognised(self):
        self.assertTrue(is_sandbox_advisory(UNCONFINED))

    def test_the_disabled_by_configuration_note_is_recognised(self):
        self.assertTrue(is_sandbox_advisory(DISABLED))

    def test_a_real_failure_is_not_an_advisory(self):
        for message in (
            "git rev-parse failed: unknown revision",
            "no changed Python functions or classes were extracted from diff.",
            "budget exhausted after 4 requests",
            "",
        ):
            with self.subTest(message=message):
                self.assertFalse(is_sandbox_advisory(message))


class UnmeasuredReasonPrefersTheStatus(unittest.TestCase):
    def test_the_advisory_never_becomes_the_reason(self):
        reason = unmeasured_reason("below_risk_threshold", [UNCONFINED])
        self.assertEqual(reason, "below_risk_threshold")
        self.assertNotIn("unconfined", reason)

    def test_the_advisory_is_skipped_even_when_it_is_first(self):
        reason = unmeasured_reason("ok", [UNCONFINED, "budget exhausted"])
        self.assertEqual(reason, "budget exhausted")

    def test_the_status_is_preferred_over_a_real_error_but_keeps_it(self):
        reason = unmeasured_reason("git_failed", ["fatal: bad object abc123"])
        self.assertEqual(reason, "git_failed: fatal: bad object abc123")

    def test_an_advisory_only_run_says_so_rather_than_inventing_a_cause(self):
        reason = unmeasured_reason("ok", [UNCONFINED])
        self.assertEqual(reason, NO_CAUSE)
        self.assertNotIn("unconfined", reason)

    def test_no_errors_at_all_is_still_answerable(self):
        self.assertEqual(unmeasured_reason("ok", []), NO_CAUSE)
        self.assertEqual(unmeasured_reason("ok", None), NO_CAUSE)

    def test_sandbox_unavailable_is_a_status_so_it_survives(self):
        # The one case where the sandbox really is the cause: mode 'required'
        # with no backend, where the pipeline returned before running anything.
        # It is distinguished by the status, never by the advisory string.
        self.assertEqual(
            unmeasured_reason("sandbox_unavailable", [UNCONFINED]),
            "sandbox_unavailable",
        )


class UnmeasuredCauseHistogram(unittest.TestCase):
    @staticmethod
    def _row(status, diff_status):
        row = BugResult(project="youtube-dl", bug_id="1", status=status)
        row.diff_status = diff_status
        return row

    def test_only_not_measured_rows_are_counted(self):
        rows = [
            self._row("not_measured", "below_risk_threshold"),
            self._row("not_measured", "below_risk_threshold"),
            self._row("not_measured", "no_targets_after_ranking"),
            self._row("caught", "ok"),
            self._row("missed", "ok"),
            self._row("git_failed", "git_failed"),
            self._row("commits_missing", "ok"),
        ]
        self.assertEqual(
            tally(rows),
            {"below_risk_threshold": 2, "no_targets_after_ranking": 1},
        )

    def test_an_empty_run_has_no_causes(self):
        self.assertEqual(tally([]), {})

    def test_summarize_publishes_the_histogram_beside_the_rate(self):
        rows = [self._row("not_measured", "below_risk_threshold") for _ in range(20)]
        summary = summarize(rows)
        self.assertEqual(summary["completion_rate"], 0.0)
        self.assertEqual(summary["unmeasured_causes"], {"below_risk_threshold": 20})


class DefaultsAreUnchanged(unittest.TestCase):
    def test_the_default_risk_threshold_is_still_the_shipped_one(self):
        default = inspect.signature(evaluate_one).parameters["risk_threshold"].default
        self.assertEqual(default, 0.35)


if __name__ == "__main__":
    unittest.main()
