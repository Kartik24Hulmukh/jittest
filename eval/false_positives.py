"""Measure a precision-screening proxy without fabricating a zero rate.

Method: run jittest over older, apparently uneventful merge commits. A surfaced
claim is a candidate false positive, not ground truth: merged code may contain
latent defects and later fixes may not use recognisable commit-message
keywords. Every claim requires blinded adjudication.

This is the mirror of run_bugsinpy.py. Recall without precision is marketing.
Meta's JiTTest evaluation emphasized reduced human review load, so an honest
precision instrument is launch-critical.

Usage:
    python eval/false_positives.py --repo ~/src/requests --count 40

    # Dry run (no network, no key, no cost):
    python eval/false_positives.py --repo ~/src/requests --count 5 --dry-run

Selection heuristic: merge commits inside the settling window whose own merge
subject does not contain revert, hotfix, regression, or rollback, and whose
diff touches at least one Python file. This does not prove cleanliness and must
not be described as doing so.

On zero findings: a run that surfaces no claims does not have a 0% false
positive rate. It has an *unknown* rate whose 95% upper bound is 3/n (the rule
of three). At n=30 that bound is 10%, which is consistent with a tool that is
wrong on one PR in ten. Every rate emitted by this module therefore carries an
upper bound, and the two must be quoted together. Publishing the point estimate
alone is the precision-side equivalent of writing RESULTS.md before a sweep
exists.

On collapse: withholding a rate is necessary and not sufficient. A run that
measures 3 of 32 PRs has told you nothing unless it also tells you what
happened to the other 29. The same instrument scored 32/40 on youtube-dl and
3/32 on requests; one of those is a fact about jittest and the other is a fact
about a repository, and an artifact that cannot separate them is a dead end.
Every non-result now names its dominant cause.

On diagnosis: naming ``no_model_requests`` as the dominant cause is still only
a symptom. A requests run produced ``diff_status: "ok"`` on 30 of 32 rows while
making zero model requests on 29 of them. The diff was read, the pipeline
decided there was nothing worth asking about, and the artifact could not say
why. That gap was immediately filled with a guess - that ranking had rejected
every changed symbol - which the same artifact refutes, because rows rejected
by ranking carry ``below_risk_threshold`` or ``all_targets_ignored``, not
``ok``. The bucket is therefore split by the funnel the pipeline already
computes, and the residual case says out loud that it does not know.

On eligibility: the split finished the trace, and the answer was that nothing
was broken. The dominant bucket became ``no_targets_after_ranking``, and the
first row traced by hand had changed exactly one file,
``.github/workflows/publish.yml``. No Python, no functions, no targets. jittest
did the right thing and the harness scored it as a failed measurement.

That is a denominator defect, and it is more dangerous than the two bugs above
it, because it does not withhold a number - it produces a wrong one that looks
reasonable. A completion rate of 0.094 divided by 32 PRs that were never
eligible was reporting requests' merge habits as a property of jittest. The
same arithmetic infects the published youtube-dl bound: the rule of three uses
n, and a smaller eligible n makes 3/n larger, so the widely-quoted 9.4% figure
was too tight and the screened figure is looser, not tighter. Any recomputation
that produces a tighter bound has changed a second variable and is wrong.

Selection now screens on Python content. Because shrinking a denominator makes
a gate easier to pass, the fix ships with a floor as well as a filter: see
``MIN_ELIGIBLE_SAMPLE``. A filter alone would have turned a visible collapse
into an invisible three-sample success.

On the window: screening worked and immediately exposed the next constraint.
On requests, 40 candidate merges yielded 6 eligible PRs, so a floor of 20 is
unreachable and the harness is now correctly refusing to publish while also
being structurally unable to ever publish. On flask the same screening barely
moved the completion rate at all - 40 eligible, 14 measured - which separates
two problems that had been confused for one: sample availability, addressed
here, and measurement rate on eligible PRs, which is a real property of jittest
and is not addressed here.

Sample availability traces to one hardcoded pair of git arguments. The
ninety-day lag is not arbitrary; it is the settling time that gives
"apparently uneventful" its meaning, because a merge from last week has not yet
had the chance to be reverted. So the default does not move. The window becomes
an explicit parameter that is recorded in the artifact, and any run that
narrows it must say so in the sentence it publishes.

On names: the sixth version of this mistake was not in a number at all, it was
in a label. A run over 40 flask merges reported ``model_requests_total: 0`` and
``targets_but_no_candidates: 25`` in the same object. The second name asserts
that generation was reached and declined; the first says nothing was ever
asked. A reader given both believed the more specific one and reported a cause
the data did not contain. A bucket name is an assertion, it is published
wherever the histogram is published, and it must claim no more than the funnel
recorded. See ``NO_CANDIDATES``.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path

MIN_COMPLETION_RATE = 0.80
SUSPECT = re.compile(r"\b(revert|hotfix|regression|rollback)\b", re.I)

# Two-sided 95% normal quantile, used for the Wilson interval.
Z_95 = 1.959964

# The settling window.
#
# DEFAULT_UNTIL is the load-bearing half. "Apparently uneventful" is a proxy
# for "nobody has had to fix this yet", and that proxy is worthless without
# elapsed time: a merge from last week has not had the opportunity to be
# reverted, so counting it as clean assumes the conclusion. Ninety days is a
# judgement call, not a derived constant, which is exactly why it now has to
# be stated in the artifact rather than buried in a git invocation.
#
# DEFAULT_SINCE bounds the other end so the sample reflects the codebase as it
# is maintained today rather than as it was five years ago.
DEFAULT_SINCE = "2.years"
DEFAULT_UNTIL = "90.days"

# The smallest eligible sample this module will let anyone publish from.
#
# Screening ineligible PRs out of the denominator is correct and it is also
# exactly the kind of change that turns a loud failure into a quiet false
# success: three eligible PRs, three measured, completion 1.00, gate green.
# At n=20 with zero findings the rule of three still only bounds the rate
# below 15%, which is honest about how little twenty PRs can establish.
MIN_ELIGIBLE_SAMPLE = 20

# A row that raised nothing but also called nothing. Distinct from an
# exception: the pipeline decided there was no work, which is a different
# diagnosis from the pipeline breaking.
#
# These are ordered from most to least informative. The residual one is a
# confession, not a cause: it means the funnel counts were absent or mutually
# inconsistent and the artifact cannot say which of the others happened.
NO_TARGETS = "no_targets_after_ranking"

# Defect 76. This bucket was called "targets_but_no_candidates", a name that
# asserts generation was reached and returned nothing. It cannot mean that.
# classify_unmeasured returns None for any row with model_requests > 0, so a
# row can only ever reach this branch having made zero requests: the model was
# never asked at all. The old name stated the opposite of what the funnel
# recorded, and a flask run of 40 PRs published it as the dominant cause of 25
# of them while model_requests_total was 0 in the same artifact. A reader
# comparing those two lines has to conclude one of them is lying.
#
# The name now claims only what is known: targets survived ranking and no
# request was sent. Why no request was sent is not known from this file, which
# is what the diagnosis_gap below is for.
NO_CANDIDATES = "generation_made_no_request"

NO_REQUESTS = "no_model_requests"

# Defect 75. classify_unmeasured returns this name on the "targets were zero
# and the diff changed no Python" path, and the name was never defined, so
# that branch raised NameError instead of returning a bucket. ci.yml runs
# `ruff check src tests` - eval/ is outside its scope, so F821 never looked at
# this file - and no test reached the branch. Both of those are why an
# undefined name survived in a module whose entire purpose is to refuse to
# report numbers it cannot support.
NO_PYTHON = "no_python_in_diff"


def upper_bound_95(observed: int, sample: int) -> float | None:
    """Return the 95% upper confidence bound on a proportion.

    For ``observed == 0`` this is the rule of three, ``3 / n``, which is the
    standard approximation to the exact binomial bound and is the number that
    matters here: it is what stops a run of zero findings being reported as a
    zero rate.

    For a non-zero count it is the upper end of the Wilson score interval,
    which stays inside [0, 1] at small samples where the normal approximation
    does not.
    """
    if sample <= 0:
        return None
    if observed <= 0:
        return round(min(1.0, 3.0 / sample), 3)
    p = observed / sample
    denominator = 1.0 + (Z_95 ** 2) / sample
    centre = p + (Z_95 ** 2) / (2 * sample)
    margin = Z_95 * math.sqrt(
        p * (1.0 - p) / sample + (Z_95 ** 2) / (4 * sample * sample)
    )
    return round(min(1.0, (centre + margin) / denominator), 3)


def window_is_default(since: str, until: str) -> bool:
    """Return True when the settling window is the one the method assumes.

    Compared as given rather than resolved to dates, because the question is
    not which instants were covered - it is whether a human overrode the
    assumption. ``--until=89.days`` is a deliberate act and is recorded as one
    even though it is a day away from the default.
    """
    return since == DEFAULT_SINCE and until == DEFAULT_UNTIL


def _as_int(value: object) -> int | None:
    """Coerce a recorded count to an int, or None if it was never recorded.

    Absent and zero must stay distinguishable. ``0`` is a measurement -
    ranking rejected everything. ``None`` is the absence of one, and the two
    lead to opposite conclusions.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def is_python_path(path: str) -> bool:
    """Return True for a path jittest could conceivably analyse.

    Deliberately narrow. A .pyi stub declares no executable behaviour to catch
    a regression in, and a .ipynb is not something the diff parser reads, so
    neither makes a PR eligible on its own.
    """
    return path.strip().endswith(".py")


def classify_unmeasured(row: dict) -> str | None:
    """Return the failure bucket for a row, or None if the row measured.

    A row measured if it made at least one model request. Everything else is
    bucketed by the furthest point the funnel reached, because that is the
    only thing that distinguishes "this repository has no risky changes" from
    "generation is broken", and those two demand opposite responses.

    Note the ordering consequence: the early return on ``model_requests > 0``
    means every branch below it describes a row that never called the model.
    No bucket returned from here may imply otherwise.
    """
    error = row.get("error")
    if error:
        return str(error).split(":", 1)[0].strip() or "Exception"
    if (_as_int(row.get("rate_limited_candidates")) or 0) > 0 or row.get("diff_status") == "rate_limited":
        return "rate_limited"
    if (_as_int(row.get("model_requests")) or 0) > 0:
        return None
    diff_status = row.get("diff_status")
    if diff_status in ("no_python_in_diff", "inverted_range", "all_targets_ignored", "below_risk_threshold", "sandbox_unavailable", "git_failed", "empty", "rate_limited"):
        return diff_status
    targets = _as_int(row.get("targets_considered"))
    candidates = _as_int(row.get("candidates_generated"))
    if targets is None:
        return NO_REQUESTS
    if targets <= 0:
        python_files = _as_int(row.get("python_files_changed"))
        if python_files == 0:
            return NO_PYTHON
        return NO_TARGETS
    if candidates is not None and candidates <= 0:
        return NO_CANDIDATES
    return NO_REQUESTS


def failure_reasons(rows: list[dict]) -> dict[str, int]:
    """Bucket every unmeasured row by cause, highest count first.

    Exceptions are keyed by their type name only. Ties are broken
    deterministically by bucket name.
    """
    counter: Counter[str] = Counter()
    for row in rows:
        bucket = classify_unmeasured(row)
        if bucket is not None:
            counter[bucket] += 1
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def telemetry_dispositions(rows: list[dict]) -> dict[str, int]:
    """Summarise candidate telemetry dispositions across all rows."""
    counter: Counter[str] = Counter()
    for row in rows:
        telemetry = row.get("telemetry", [])
        if isinstance(telemetry, list):
            for item in telemetry:
                if isinstance(item, dict):
                    disp = item.get("disposition")
                    if disp:
                        counter[disp] += 1
                elif hasattr(item, "disposition"):
                    disp = getattr(item, "disposition", None)
                    if disp:
                        counter[disp] += 1
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def summarize_rows(
    rows: list[dict],
    attempted: int,
    screened_out: int | None = None,
    window: tuple[str, str] | None = None,
) -> dict:
    """Withhold the rate when coverage is too low to support it.

    An earlier version divided by ``max(len(usable), 1)``. Zero work therefore
    printed 0.0% false positives and exited successfully. This function makes
    insufficient evidence an explicit terminal state instead.

    A second, quieter version of the same mistake survived that fix: enough
    work, no findings, and a printed ``0.000``. Zero findings is not a zero
    rate. Every rate is now accompanied by ``*_upper_bound_95`` and the two
    must be quoted together.

    A third version survived both: a run that withholds the rate, exits 1, and
    never says why coverage failed. That is a broken instrument reporting
    correctly rather than a diagnosis, so ``failure_reasons`` and
    ``dominant_failure`` are now part of every summary.

    A fourth survived all three: a dominant cause of ``no_model_requests``,
    which names where the pipeline stopped and not why. When that is still the
    dominant bucket, the summary now carries ``diagnosis_gap`` so the artifact
    states its own limit rather than leaving a reader to supply a cause.

    A fifth was not in this function at all. It was in the denominator handed
    to it: PRs that changed no Python counted as failed measurements, so a
    correct no-op looked like a broken pipeline. Selection screens them out
    now, and ``sample_floor_met`` exists so that the smaller denominator
    cannot quietly promote three eligible PRs into a publishable result.

    A sixth is what ``window`` is for. Every number above is conditional on
    which commits were eligible to be looked at, and that was decided by two
    hardcoded git arguments appearing in no output. A reader could not tell a
    run over two years of settled history from a run over last fortnight, and
    those two support very different sentences.

    A seventh was a bucket name rather than a number: see ``NO_CANDIDATES``.
    The gap it now carries exists because renaming it removed a false cause
    without supplying a true one, and an empty space is where the next guess
    goes.

    ``attempted`` is the eligible population. ``screened_out`` is how many
    candidate merges were rejected before analysis; it is reported so the
    ineligible population stays visible rather than vanishing from the record.
    ``window`` is the (since, until) pair that produced the population.
    """
    usable = [
        row for row in rows
        if "error" not in row and row.get("model_requests", 0) > 0
    ]
    noisy = [row for row in usable if row.get("reported", 0) > 0]
    completion = len(usable) / attempted if attempted else 0.0
    gate_ready = attempted > 0 and completion >= MIN_COMPLETION_RATE
    sample_floor_met = len(usable) >= MIN_ELIGIBLE_SAMPLE
    publishable = bool(gate_ready and usable)
    bound = upper_bound_95(len(noisy), len(usable)) if publishable else None
    reasons = failure_reasons(rows)
    dominant = next(iter(reasons), None)
    since, until = window if window else (DEFAULT_SINCE, DEFAULT_UNTIL)
    diagnosis_gap = None
    if dominant == NO_CANDIDATES:
        diagnosis_gap = (
            "Dominant cause is a contradiction, not a diagnosis. These rows "
            "extracted targets that survived ranking and then sent no model "
            "request, so nothing declined to generate a candidate - nothing "
            "was asked. Three paths reach here without raising: a response "
            "cache hit, a budget or request-ceiling guard that short-circuits "
            "before the first POST, and a generation step that returns empty "
            "on every ranked target. This artifact cannot say which. Re-run "
            "with the response cache disabled and read the per-row telemetry "
            "before attributing a cause, and do not read this bucket as "
            "evidence about the model or the repository."
        )
    elif dominant == NO_REQUESTS:
        diagnosis_gap = (
            "Dominant cause is undiagnosed. These rows made no model request "
            "and carry no usable funnel counts, so this artifact cannot say "
            "whether ranking rejected every changed symbol or generation was "
            "reached and produced nothing. Do not attribute a cause from this "
            "file; re-run on a build that records targets_considered and "
            "candidates_generated per row."
        )
    return {
        "prs_attempted": attempted,
        "prs_screened_out_as_ineligible": screened_out,
        "prs_analysed": len(usable),
        "prs_errored_or_unmeasured": attempted - len(usable),
        "model_requests_total": sum(
            int(row.get("model_requests", 0)) for row in rows
        ),
        "input_tokens_total": sum(
            int(row.get("input_tokens", 0)) for row in rows
        ),
        "output_tokens_total": sum(
            int(row.get("output_tokens", 0)) for row in rows
        ),
        "model_request_attempts_total": sum(
            int(row.get("model_request_attempts", 0)) for row in rows
        ),
        "rate_limited_candidates_total": sum(
            int(row.get("rate_limited_candidates", 0)) for row in rows
        ),
        "completion_rate": round(completion, 3) if attempted else None,
        "prs_with_a_report": len(noisy),
        "false_positive_rate": (
            round(len(noisy) / len(usable), 3) if publishable else None
        ),
        "false_positive_rate_upper_bound_95": bound,
        "comments_per_100_prs": (
            round(100 * len(noisy) / len(usable), 1) if publishable else None
        ),
        "comments_per_100_prs_upper_bound_95": (
            round(100 * bound, 1) if bound is not None else None
        ),
        "gate_ready": gate_ready,
        "eligible_sample_floor": MIN_ELIGIBLE_SAMPLE,
        "sample_floor_met": sample_floor_met,
        "publishable": bool(gate_ready and sample_floor_met),
        "selection_window": {"since": since, "until": until},
        "selection_window_is_default": window_is_default(since, until),
        "failure_reasons": reasons,
        "dominant_failure": dominant,
        "telemetry_disposition_breakdown": telemetry_dispositions(rows),
        "diagnosis_gap": diagnosis_gap,
        "NOTE": (
            "Rate is withheld unless at least 80% of selected PRs produced "
            "measured results. Every surfaced claim still requires blind human "
            "adjudication; an uneventful merge is not known-clean ground truth."
        ),
        "BOUND_NOTE": (
            "Quote the rate and its 95% upper bound together, always. Zero "
            "findings over n PRs is not a 0% false-positive rate; it is an "
            "unknown rate bounded above by roughly 3/n. Reporting the point "
            "estimate alone overstates what the sample can support."
        ),
        "CAUSE_NOTE": (
            "A withheld rate is not a finding. Compare dominant_failure across "
            "repositories before concluding anything about jittest: a harness "
            "that scores 32/40 on one codebase and 3/32 on another is "
            "reporting a property of the codebases until proven otherwise. "
            "Every bucket below the measured line describes a row that never "
            "called the model; none of them is evidence about the model."
        ),
        "ELIGIBILITY_NOTE": (
            "prs_attempted counts only merges whose diff touched at least one "
            "Python file. A PR that changes no Python is not a failed "
            "measurement and never enters the denominator. Any bound computed "
            "from an unscreened denominator - including the 9.4% youtube-dl "
            "figure - used too large an n and is therefore too tight. "
            "Screening makes a zero-finding bound LOOSER, never tighter; a "
            "recomputation that tightens it has moved a second variable."
        ),
        "WINDOW_NOTE": (
            "Every number here is conditional on selection_window. The until "
            "bound is the settling time that makes 'apparently uneventful' "
            "mean anything: a merge that has not had time to be reverted is "
            "not evidence of a clean merge. Narrowing it enlarges the sample "
            "by weakening the assumption the sample rests on, so a rate from "
            "a non-default window is a different measurement and must not be "
            "compared against one from the default."
        ),
    }


def _window_caveat(summary: dict) -> str:
    """Return the sentence a non-default window obliges the caller to carry.

    Appended to the published sentence rather than left in the JSON, because
    the published sentence is the part that gets copied and the JSON is the
    part that does not.
    """
    if summary.get("selection_window_is_default", True):
        return ""
    window = summary.get("selection_window") or {}
    return (
        " Measured over a non-default selection window "
        f"(since={window.get('since')}, until={window.get('until')}), which "
        "weakens the settling-time assumption behind 'uneventful'. Not "
        "comparable with default-window results."
    )


def describe(summary: dict) -> str:
    """Return the one sentence that is safe to copy into a README.

    Callers keep reaching for the bare point estimate. Give them a phrasing
    that is correct by construction so that the convenient thing and the honest
    thing are the same thing.
    """
    if not summary.get("gate_ready"):
        sentence = (
            "No false-positive rate: coverage below the "
            f"{int(MIN_COMPLETION_RATE * 100)}% completion floor "
            f"({summary.get('prs_analysed')}/{summary.get('prs_attempted')} "
            "PRs measured)."
        )
        dominant = summary.get("dominant_failure")
        if dominant:
            count = summary.get("failure_reasons", {}).get(dominant, 0)
            sentence += (
                f" Dominant cause: {dominant} "
                f"({count} of {summary.get('prs_errored_or_unmeasured')} "
                "unmeasured)."
            )
        if summary.get("diagnosis_gap"):
            sentence += " That names where the pipeline stopped, not why."
        return sentence
    analysed = summary["prs_analysed"]
    noisy = summary["prs_with_a_report"]
    bound = summary["false_positive_rate_upper_bound_95"]
    if not summary.get("sample_floor_met", True):
        return (
            f"Coverage held, but only {analysed} eligible PRs were measured, "
            f"below the floor of {summary.get('eligible_sample_floor')}. A "
            "sample this small cannot separate a good tool from a lucky one, "
            "and screening ineligible PRs out of the denominator makes small "
            "samples easy to produce. No rate is published from this run."
        )
    if noisy == 0:
        sentence = (
            f"No false positives surfaced on {analysed} apparently uneventful "
            f"merged PRs. That bounds the false-positive rate below "
            f"{bound * 100:.1f}% at 95% confidence; it does not establish that "
            "the rate is zero."
        )
    else:
        rate = summary["false_positive_rate"]
        sentence = (
            f"{noisy} of {analysed} apparently uneventful merged PRs surfaced "
            f"a claim: a candidate false-positive rate of {rate * 100:.1f}% "
            f"(95% upper bound {bound * 100:.1f}%). Each claim requires blind "
            "adjudication before it counts as a false positive."
        )
    return sentence + _window_caveat(summary)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout


def changed_python_files(repo: Path, base: str, head: str) -> list[str]:
    """Return the Python files changed between two commits.

    An empty list means the PR could not have produced a finding no matter how
    good the tool is, which makes it ineligible rather than unmeasured.
    """
    out = git(repo, "diff", "--name-only", base, head)
    return [line for line in out.splitlines() if is_python_path(line)]


def select_pairs(
    repo: Path,
    count: int,
    require_python: bool = True,
    since: str = DEFAULT_SINCE,
    until: str = DEFAULT_UNTIL,
) -> tuple[list[tuple[str, str]], int]:
    """Return eligible (base, head) pairs and how many were screened out.

    The screened-out count is returned rather than discarded because a
    denominator that silently shrinks is how a collapsed run turns into a
    clean-looking one.

    ``since`` and ``until`` were hardcoded until a screened run on requests
    yielded 6 eligible PRs against a floor of 20, making the gate unreachable
    rather than merely unmet. They are parameters now, with the defaults
    unchanged, so that widening the sample is a recorded decision rather than
    an edit to this file.
    """
    log = git(
        repo,
        "log",
        "--merges",
        f"--since={since}",
        f"--until={until}",
        "--pretty=%H%x00%P%x00%s",
    ).strip().splitlines()
    pairs: list[tuple[str, str]] = []
    screened_out = 0
    for line in log:
        parts = line.split("\x00")
        if len(parts) != 3:
            continue
        _sha, parents, subject = parts
        if SUSPECT.search(subject):
            continue
        parent_shas = parents.split()
        if len(parent_shas) != 2:
            continue
        base, head = parent_shas[0], parent_shas[1]
        if require_python and not changed_python_files(repo, base, head):
            screened_out += 1
            continue
        pairs.append((base, head))
        if len(pairs) >= count:
            break
    return pairs, screened_out


def clean_merges(
    repo: Path,
    count: int,
    require_python: bool = True,
    since: str = DEFAULT_SINCE,
    until: str = DEFAULT_UNTIL,
) -> list[tuple[str, str]]:
    """Return (base_sha, head_sha) pairs for apparently uneventful merges."""
    return select_pairs(
        repo, count, require_python=require_python, since=since, until=until
    )[0]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Screen precision on apparently uneventful merged PRs"
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--model", default=None)
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument(
        "--out", type=Path, default=Path("false-positives.json")
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run with a stub model: no network, no key, no cost",
    )
    parser.add_argument(
        "--no-python-filter", action="store_true",
        help=(
            "Reproduce pre-screening selection, including PRs that change no "
            "Python. Diagnostic only: the resulting denominator is wrong."
        ),
    )
    parser.add_argument(
        "--since", default=DEFAULT_SINCE,
        help=(
            "Oldest commits to consider, as a git --since expression "
            f"(default: {DEFAULT_SINCE}). Widening this is safe."
        ),
    )
    parser.add_argument(
        "--until", default=DEFAULT_UNTIL,
        help=(
            "Settling time a merge must have survived, as a git --until "
            f"expression (default: {DEFAULT_UNTIL}). Narrowing this enlarges "
            "the sample by weakening the assumption it rests on, and is "
            "recorded in the artifact and in the published sentence."
        ),
    )
    args = parser.parse_args()

    from jittest.config import load_config
    from jittest.llm import build_llm
    from jittest.pipeline import run as run_pipeline

    pairs, screened_out = select_pairs(
        args.repo,
        args.count,
        require_python=not args.no_python_filter,
        since=args.since,
        until=args.until,
    )
    rows: list[dict] = []
    for base, head in pairs:
        try:
            overrides = {
                "budget_usd": args.budget,
                "max_targets": 5,
                "candidates_per_target": 4,
                "risk_threshold": 0.35,
            }
            if args.model is not None:
                overrides["model"] = args.model
            cfg = load_config(args.repo, overrides=overrides)
            llm = build_llm(
                cfg.model,
                dry_run=args.dry_run,
                budget_usd=cfg.budget_usd,
                temperature=cfg.temperature,
                request_ceiling=cfg.max_targets * cfg.candidates_per_target + 5,
            )
            report = run_pipeline(
                repo=args.repo, base=base, head=head, cfg=cfg, llm=llm
            )
            reported = [
                finding for finding in report.findings
                if finding.assessment.should_report
            ]
            rows.append({
                "base": base[:8],
                "head": head[:8],
                "reported": len(reported),
                "cost_usd": report.cost_usd,
                "priced": report.priced,
                "input_tokens": getattr(report, "input_tokens", 0),
                "output_tokens": getattr(report, "output_tokens", 0),
                "model_requests": getattr(report, "model_requests", 0),
                "diff_status": getattr(report, "diff_status", None),
                # The funnel. Without these two a zero-request row is
                # undiagnosable, and an undiagnosable row invites a guess.
                "targets_considered": getattr(
                    report, "targets_considered", None
                ),
                "candidates_generated": getattr(
                    report, "candidates_generated", None
                ),
                "python_files_changed": len(
                    changed_python_files(args.repo, base, head)
                ),
                "model": cfg.model,
                "claims": [
                    finding.assessment.summary for finding in reported
                ],
                "telemetry": [item.as_dict() for item in report.telemetry],
            })
        except Exception as exc:  # noqa: BLE001 - preserve all selected rows
            rows.append({
                "base": base[:8],
                "head": head[:8],
                "error": f"{type(exc).__name__}: {exc}",
                "model_requests": 0,
            })

    summary = summarize_rows(
        rows,
        len(pairs),
        screened_out=screened_out,
        window=(args.since, args.until),
    )
    args.out.write_text(
        json.dumps({"summary": summary, "results": rows}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    print()
    print(describe(summary))
    if not summary["gate_ready"]:
        print(
            "FAIL: insufficient measured PRs; refusing to publish a "
            "false-positive rate"
        )
        return 1
    if not summary["sample_floor_met"]:
        print(
            "FAIL: eligible sample below "
            f"{MIN_ELIGIBLE_SAMPLE}; refusing to publish a false-positive rate"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
