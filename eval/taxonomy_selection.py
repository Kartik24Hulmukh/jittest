"""Choose which rows a ranking verdict is allowed to describe.

``distribution_verdict`` raises ``ContaminatedPopulation`` if it is handed a
score at or above the threshold. That guard is correct and it is also, on its
own, unsatisfiable.

``classify_row`` defines four causes, and one of them is
``SCORED_BUT_NOT_ANALYSED``: a row that was never analysed *and* scored at or
above the cutoff, because ranking accepted it and a path filter, a target cap
or a budget rejected it afterwards. Such a row is genuinely unmeasured. So the
honest unmeasured population routinely contains scores above the threshold,
and a caller doing exactly the right thing - take the unmeasured rows, pass
their scores - is met with an exception.

The guard cannot tell that caller apart from the Session T mistake of passing
the *analysed* rows, because a bare ``list[float]`` carries no provenance. A
score of 0.60 does not record whether ranking accepted it or whether something
downstream did. The discriminator is not the value. It is the cause.

So the selection moves up a level, to here. ``verdict_for_rows`` passes only
the rows whose cause is ``ALL_BELOW_THRESHOLD`` - the actual ranking
rejections - and by construction every one of those is below the cutoff. The
guard then cannot fire on correct usage and still fires loudly on the wrong
population.

Everything else is reported beside the verdict as a count, never inside it. A
row that ranking accepted is not evidence about ranking, and letting it move
ranking's median - in either direction - is the same class of error as
quoting a maximum to describe a sample.
"""
from __future__ import annotations

from failure_taxonomy import (  # noqa: F401
    ALL_BELOW_THRESHOLD,
    CAUSE_NOT_RECORDED,
    DEFAULT_RISK_THRESHOLD,
    NO_FUNCTIONS_EXTRACTED,
    SCORED_BUT_NOT_ANALYSED,
    _as_float,
    classify_row,
    distribution_verdict,
)

# The only cause whose scores describe what ranking did. Deliberately a tuple
# of one rather than an inline comparison, so that adding a second ranking
# cause later is a visible edit here instead of a silent widening somewhere.
RANKING_REJECTION_CAUSES = (ALL_BELOW_THRESHOLD,)


def ranking_rejection_scores(
    rows: list[dict], threshold: float = DEFAULT_RISK_THRESHOLD
) -> list[float]:
    """Top-scores of the rows ranking actually rejected.

    A row is included only when ``classify_row`` says the reason it went
    unanalysed was that every score fell short. Rows that were analysed, rows
    that were filtered downstream, rows with no extracted functions and rows
    whose cause was never recorded are all excluded - not because they do not
    matter, but because none of them is a statement about the cutoff.
    """
    out: list[float] = []
    for row in rows:
        if classify_row(row, threshold=threshold) not in RANKING_REJECTION_CAUSES:
            continue
        score = _as_float(row.get("top_risk_score"))
        if score is not None:
            out.append(score)
    return out


def verdict_for_rows(
    rows: list[dict], threshold: float = DEFAULT_RISK_THRESHOLD
) -> dict:
    """Describe the ranking rejections, and count everything else separately.

    Returns the ``distribution_verdict`` for the ranking-rejection rows under
    ``verdict``, plus explicit counts for the causes that were held out. The
    counts are returned rather than logged because a population that was 40%
    downstream-filtered is a different finding from one that was 0%, and the
    reader cannot know which they are looking at from a median alone.

    ``excluded_from_verdict`` is the number of unanalysed rows this verdict is
    silent about. If it is large, the verdict is narrow, and saying so is the
    entire job of this function.
    """
    causes: dict[str, int] = {}
    analysed = 0
    for row in rows:
        cause = classify_row(row, threshold=threshold)
        if cause is None:
            analysed += 1
            continue
        causes[cause] = causes.get(cause, 0) + 1

    scores = ranking_rejection_scores(rows, threshold=threshold)
    unanalysed = sum(causes.values())
    ranking_rejections = causes.get(ALL_BELOW_THRESHOLD, 0)

    return {
        "rows_seen": len(rows),
        "rows_analysed": analysed,
        "rows_unanalysed": unanalysed,
        "ranking_rejections": ranking_rejections,
        "scored_but_not_analysed": causes.get(SCORED_BUT_NOT_ANALYSED, 0),
        "no_functions_extracted": causes.get(NO_FUNCTIONS_EXTRACTED, 0),
        "cause_not_recorded": causes.get(CAUSE_NOT_RECORDED, 0),
        "excluded_from_verdict": unanalysed - ranking_rejections,
        "verdict": distribution_verdict(scores, threshold=threshold),
        "SCOPE_NOTE": (
            "The verdict describes ranking rejections only. Rows that scored "
            "at or above the cutoff and were stopped downstream are counted "
            "here and excluded from it deliberately: ranking accepted them, "
            "so they say nothing about where the cutoff should sit."
        ),
    }
