"""Decide *why* a PR went unanalysed, arithmetically rather than by eye.

This module exists because of one sentence in a Lane R12 report:

    "The scores of evaluable changed Python functions in unmeasured flask PRs
     are clustered just under the 0.35 threshold (reaching 0.3272 ... and
     0.3200 ...), indicating that routine refactoring falls marginally below
     the risk ranking cutoff rather than being far below it."

The distribution reported two lines above it was: min 0.0000, median 0.0577,
max 0.3969, over 26 rows.

A median of 0.0577 is not marginally below 0.35. It is 16% of it. The sentence
was built by quoting the two highest values in the sample to describe where the
sample sits, which is the most natural mistake in the world to make and also
the one that ends with someone lowering a threshold to 0.30 because "we were
so close". Nobody lied. The arithmetic simply was not done, and prose does not
force anyone to do it.

So the verdict becomes a function. ``distribution_verdict`` will not return
"clustered near the threshold" unless the median is genuinely near it, and the
sentence it emits quotes the median first and the maximum last.

Two defects were also sitting unremarked in the same tables.

**The bucket is contaminated.** The reported maximum, 0.3969, is *above* the
0.35 cutoff, and it occurs twice in a ten-row sample. A function that scored
above the threshold was not rejected by ranking - it was excluded afterwards,
by a path filter, a target cap, or a budget. Those rows were nonetheless
counted in ``no_targets_after_ranking``. The dominant cause of the flask
collapse is therefore wrong by at least two rows and by an unknown amount in
full, and the fix is not to recount by hand but to stop one bucket standing in
for four unrelated situations.

**Extraction and screening disagree.** Six of the ten sampled rows report zero
changed Python functions against diffs of 2000-2700 insertions across 50-58
files. Every one of those rows passed the PR #85 eligibility screen, which
means ``git diff --name-only`` found at least one ``.py`` path in it. So git
says there is Python and the extractor says there are no functions. One of
them is wrong, and until that is settled every statement about ranking rests
on a set of targets that may never have been built. This module cannot resolve
it - it can only refuse to let it keep hiding inside a bucket named after
ranking.

Nothing here changes a threshold or a weight. Characterise first. A threshold
tuned before its inputs are trusted is not a calibration, it is a wish.
"""
from __future__ import annotations

from statistics import median as _median

# The production default. Imported as a value rather than hardcoded at each
# call site so that a future change to jittest's own default cannot silently
# leave this analysis describing a cutoff that no longer exists.
DEFAULT_RISK_THRESHOLD = 0.35

# How close to the threshold a score has to be before "nearly made it" is a
# fair description of it. Deliberately generous: at 0.10 a score of 0.25 still
# counts as near, and the flask median of 0.0577 still does not.
NEAR_BAND = 0.10

# Causes. Four situations that were previously one bucket, ordered by how
# differently they have to be answered.
#
# NO_FUNCTIONS_EXTRACTED  -> a parser bug, or a screening bug. An engineering
#                            defect either way, and the only one of the four
#                            that means the tool is broken.
# ALL_BELOW_THRESHOLD     -> ranking worked and said no. A calibration
#                            question, answerable only once the population is
#                            trustworthy.
# SCORED_BUT_NOT_ANALYSED -> ranking said yes and something downstream said no:
#                            path filter, target cap, budget. Not a ranking
#                            result at all, and the reason the old bucket was
#                            contaminated.
# CAUSE_NOT_RECORDED      -> the artifact does not know. Kept as an explicit
#                            outcome so that ignorance never gets rounded into
#                            whichever neighbouring cause sounds plausible.
NO_FUNCTIONS_EXTRACTED = "no_functions_extracted"
ALL_BELOW_THRESHOLD = "all_scores_below_threshold"
SCORED_BUT_NOT_ANALYSED = "scored_but_not_analysed"
CAUSE_NOT_RECORDED = "cause_not_recorded"


def _as_float(value: object) -> float | None:
    """Coerce a recorded score, keeping absent distinguishable from zero.

    0.0 is a measurement: ranking scored the function and scored it at nothing.
    None is the absence of one. Collapsing them is how a missing field becomes
    a confident claim about a low score.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_row(
    row: dict, threshold: float = DEFAULT_RISK_THRESHOLD
) -> str | None:
    """Return the cause a row went unanalysed, or None if it was analysed.

    Requires ``functions_extracted`` and ``top_risk_score`` on the row. When
    either is missing the answer is ``CAUSE_NOT_RECORDED`` and not a guess:
    the whole point of splitting the bucket is defeated if the split itself
    starts inferring.
    """
    if (_as_int(row.get("model_requests")) or 0) > 0:
        return None

    functions = _as_int(row.get("functions_extracted"))
    top = _as_float(row.get("top_risk_score"))
    python_files = _as_int(row.get("python_files_changed"))

    if functions is None:
        return CAUSE_NOT_RECORDED

    if functions <= 0:
        # Eligibility screening already established that git saw Python in
        # this diff. Zero extracted functions therefore contradicts the
        # screen rather than explaining the row.
        if python_files is not None and python_files > 0:
            return NO_FUNCTIONS_EXTRACTED
        return CAUSE_NOT_RECORDED

    if top is None:
        return CAUSE_NOT_RECORDED

    if top >= threshold:
        # Ranking accepted it. Whatever stopped this row, it was not ranking,
        # and filing it under a ranking bucket is how a wrong dominant cause
        # gets published.
        return SCORED_BUT_NOT_ANALYSED

    return ALL_BELOW_THRESHOLD


def distribution_verdict(
    scores: list[float], threshold: float = DEFAULT_RISK_THRESHOLD
) -> dict:
    """Describe where a set of top-scores actually sits relative to a cutoff.

    The verdict keys on the **median**, not the maximum. Quoting the two
    highest values of a 26-row sample and calling the sample "clustered just
    under" the cutoff is not a lie and it is not a rounding error; it is the
    single most persuasive way to argue for lowering a threshold, and it is
    persuasive precisely because every number in it is true.

    Zeros are kept in the population. A row that produced no score is part of
    what the ranker did to this repository, and dropping them is a second way
    to move the centre upward without appearing to.
    """
    clean = [value for value in (
        _as_float(score) for score in scores
    ) if value is not None]

    if not clean:
        return {
            "n": 0,
            "verdict": "no_scores",
            "sentence": (
                "No scores were recorded, so nothing can be said about where "
                "they sit relative to the threshold."
            ),
        }

    low = min(clean)
    mid = float(_median(clean))
    high = max(clean)
    near = [value for value in clean if threshold - NEAR_BAND <= value < threshold]
    over = [value for value in clean if value >= threshold]
    zeros = [value for value in clean if value == 0.0]

    clustered = mid >= threshold - NEAR_BAND
    verdict = "clustered_near_threshold" if clustered else "far_below_threshold"

    if clustered:
        sentence = (
            f"Median top-score {mid:.4f} sits within {NEAR_BAND:.2f} of the "
            f"{threshold:.2f} threshold across {len(clean)} rows. These "
            "changes were close to being analysed, so threshold calibration "
            "is a legitimate question to open."
        )
    else:
        sentence = (
            f"Median top-score {mid:.4f} across {len(clean)} rows, against a "
            f"threshold of {threshold:.2f}. The centre of this population is "
            "nowhere near the cutoff, so these changes were not narrowly "
            f"missed. The maximum of {high:.4f} describes one row, not the "
            "sample, and must not be quoted as though it did."
        )

    if over:
        sentence += (
            f" {len(over)} row(s) scored at or above the threshold "
            f"(max {high:.4f}); those were not rejected by ranking and do not "
            "belong in a ranking-failure bucket at all."
        )

    return {
        "n": len(clean),
        "threshold": threshold,
        "min": round(low, 4),
        "median": round(mid, 4),
        "max": round(high, 4),
        "zero_score_rows": len(zeros),
        "near_threshold_rows": len(near),
        "at_or_above_threshold_rows": len(over),
        "population_contaminated": bool(over),
        "verdict": verdict,
        "sentence": sentence,
        "MEDIAN_NOTE": (
            "The verdict keys on the median. A maximum is one row. Describing "
            "a sample by its largest member is the standard way an argument "
            "for lowering a threshold gets assembled out of true numbers."
        ),
        "CONTAMINATION_NOTE": (
            "Any score at or above the threshold proves the row was not a "
            "ranking rejection. If at_or_above_threshold_rows is non-zero, the "
            "bucket these rows came from is mislabelled and its count is "
            "wrong by at least that many."
        ),
    }


def reasons(
    rows: list[dict], threshold: float = DEFAULT_RISK_THRESHOLD
) -> dict[str, int]:
    """Bucket unanalysed rows by cause, highest count first."""
    counts: dict[str, int] = {}
    for row in rows:
        cause = classify_row(row, threshold=threshold)
        if cause is not None:
            counts[cause] = counts.get(cause, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def extraction_disagreements(rows: list[dict]) -> list[dict]:
    """Return rows where git found Python and the extractor found no functions.

    Surfaced as its own list rather than only as a count, because this is the
    one cause in the taxonomy that means something is broken. A count invites
    a shrug; a list of SHAs invites a look.
    """
    out = []
    for row in rows:
        functions = _as_int(row.get("functions_extracted"))
        python_files = _as_int(row.get("python_files_changed"))
        if functions == 0 and (python_files or 0) > 0:
            out.append({
                "base": row.get("base"),
                "head": row.get("head"),
                "python_files_changed": python_files,
                "functions_extracted": functions,
            })
    return out
