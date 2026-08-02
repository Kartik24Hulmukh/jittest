"""Why a bug went unmeasured, answered from the status rather than a string.

Defect 74.

``jittest.pipeline.run`` copies every sandbox note into ``report.errors``
whenever no isolation backend is available::

    for note in sbx.notes:
        emit(note)
        if not sbx.isolated:
            report.errors.append(note)

On a stock GitHub runner there is no backend that satisfies the auto-mode
image check, so that append happens on every bug of every run. Meanwhile
``run_bugsinpy.evaluate_one`` recorded ``report.errors[0]`` as the cause of any
bug that came back unmeasured. The two together guarantee that the recorded
cause of an unmeasured bug is a confinement advisory, on every row, whatever
the real reason was.

Run 30754409055 is the receipt: twenty youtube-dl bugs attempted, zero
measured, and the summary read as eighteen sandbox failures and two below the
risk threshold. The eighteen were not sandbox failures. An unconfined
candidate still executes; the advisory says only that it executed without a
namespace around it. The real cause was sitting unread in
``Report.diff_status``, which is a closed vocabulary set at the point of the
decision:

    ok, empty, git_failed, all_targets_ignored, below_risk_threshold,
    sandbox_unavailable, inverted_range, no_python_in_diff,
    no_targets_after_ranking

So the rule here is: the status is the cause, an error string may add detail
the status cannot carry, and an advisory is never a cause.

The cost of getting this wrong is a wrong next action. The published plan
after run 30754409055 opened with 'start the Docker daemon'. Starting a Docker
daemon would not have measured one additional bug.
"""
from __future__ import annotations

# Substrings that identify a confinement notice rather than a failure. Matched
# as substrings, not compared whole, because the note is formatted with the
# backend name and the image name interpolated into it.
SANDBOX_ADVISORY_MARKERS = (
    "ran unconfined",
    "sandbox disabled by configuration",
    "no container or namespace backend found",
)

NO_CAUSE = "model was never called and the pipeline reported no cause"


def is_sandbox_advisory(message: str) -> bool:
    """True if ``message`` is a confinement notice rather than a failure.

    A sandbox advisory is worth printing and worth counting. It is never the
    reason a bug went unmeasured, because an unconfined candidate still runs.
    """
    low = (message or "").lower()
    return any(marker in low for marker in SANDBOX_ADVISORY_MARKERS)


def unmeasured_reason(diff_status: str, errors: list[str] | None) -> str:
    """The reason one bug was not measured, most authoritative source first.

    ``diff_status`` wins over any error string because it is a closed
    vocabulary set at the point of the decision, whereas an error string is
    free text appended by whichever stage spoke last. Error strings are used
    only to add detail the status cannot carry, and advisories are skipped
    entirely.

    ``sandbox_unavailable`` is the one status where the sandbox genuinely is
    the cause: it is only ever set when mode is 'required' and no backend
    could be found, in which case the pipeline returned before running
    anything. That case is distinguished by the status, not by the string.
    """
    real = [e for e in (errors or []) if e and not is_sandbox_advisory(e)]
    if diff_status and diff_status != "ok":
        return f"{diff_status}: {real[0]}" if real else diff_status
    if real:
        return real[0]
    return NO_CAUSE


def tally(rows: list) -> dict:
    """Histogram of ``diff_status`` over rows whose status is ``not_measured``.

    Only not_measured rows are counted. ``git_failed`` and ``commits_missing``
    are already reported by name and are already excluded from the catch-rate
    denominator, so folding them in here would double-count them.

    Takes any object with ``.status`` and ``.diff_status`` so that this stays
    testable without constructing a whole eval run.
    """
    causes: dict[str, int] = {}
    for row in rows:
        if getattr(row, "status", None) != "not_measured":
            continue
        key = getattr(row, "diff_status", "") or "unknown"
        causes[key] = causes.get(key, 0) + 1
    return dict(sorted(causes.items()))
