"""Vary one knob, hold everything else, and let the result refute a hypothesis.

Why this exists.

A precision run over 40 ``pallets/flask`` merges produced
``model_requests_total: 0``. Twenty-five of the forty unmeasured rows had
extracted targets that survived ranking and then sent no request. That is the
whole finding: the model is almost never being asked, and until somebody knows
why, no catch rate and no false-positive rate can exist, because both are
ratios over rows that reached the model.

There is an obvious suspect. ``risk_threshold`` defaults to 0.35, and
``risk.py`` halves the score of any target with ``churn <= 2`` that does not
modify existing code. A repository of small, tidy merges could plausibly have
every changed symbol scored below the bar. Obvious suspects are exactly the
ones that need a control, because an obvious suspect that is never tested
becomes a fact by repetition - which is how this project acquired six
retracted numbers.

So: run the same PRs, in the same order, with the same model, changing only
the threshold. Three rungs, descending. Because the bottom rung is 0.0, which
admits every extracted target with no filtering whatsoever, the experiment
cannot come back ambiguous:

    If requests are still zero at threshold 0.0, the risk gate is not the
    constraint and the defect is upstream of it - in diff.extract_targets,
    in ranking, or in the generation call itself.

That sentence is written here, in the source, before any run. It is also
emitted into the artifact by ``refutation_condition()`` so it cannot be
quietly reinterpreted after the numbers arrive. This module's opinion of the
result is fixed in advance; only the data is allowed to vary.

Usage. Run it as a module, not as a script path. This file imports from
``eval.false_positives``, and ``python eval/fp_ladder.py`` puts ``eval/`` on
sys.path rather than the repository root, so the sibling import fails before
argparse is reached. ``-m`` from the repository root resolves it::

    PYTHONPATH=src python -m eval.fp_ladder --repo ~/src/flask --count 40 \\
        --model moonshotai/kimi-k3-free --thresholds 0.35,0.15,0.0

    # No network, no key, no cost - proves the harness runs end to end:
    PYTHONPATH=src python -m eval.fp_ladder --repo ~/src/flask --count 5 \\
        --dry-run

What this module deliberately does not do: publish a false-positive rate.
That remains the job of false_positives.py and its floors. This is a
diagnostic instrument for one question, and a diagnostic that starts
reporting headline numbers stops being trustworthy at both jobs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval.false_positives import (
    DEFAULT_SINCE,
    DEFAULT_UNTIL,
    changed_python_files,
    describe,
    select_pairs,
    summarize_rows,
)

DEFAULT_THRESHOLDS = "0.35,0.15,0.0"

# Verdicts. Deliberately not booleans: "the gate was not the problem" and "the
# gate was the problem" are not the only two outcomes, and collapsing them
# into a flag is how a third outcome gets misfiled as one of the first two.
UPSTREAM = "upstream_of_the_gate"
GATE_WAS_BINDING = "gate_was_binding"
GATE_NOT_BINDING = "gate_was_not_binding"
INCONCLUSIVE = "inconclusive"


def parse_thresholds(raw: str) -> list[float]:
    """Return thresholds in descending order, deduplicated.

    Descending because the hypothesis is monotone: loosening a filter can only
    admit more targets, never fewer. Presenting the rungs in that order makes
    a non-monotone result visible as the anomaly it would be, rather than
    something a reader has to reconstruct by sorting a table.
    """
    values: list[float] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        value = float(chunk)
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"threshold {value} is outside [0.0, 1.0]; risk scores are "
                "normalised and a bound outside that range silently admits "
                "everything or nothing"
            )
        if value not in values:
            values.append(value)
    if not values:
        raise ValueError("no thresholds given")
    return sorted(values, reverse=True)


def refutation_condition(thresholds: list[float]) -> str:
    """Return the sentence that decides the experiment, before it is run."""
    floor = min(thresholds)
    if floor > 0.0:
        return (
            f"Lowest rung is {floor}, not 0.0, so a zero-request result at "
            "the bottom does not exonerate the risk gate: some targets may "
            "still be filtered. Re-run including 0.0 before drawing a "
            "conclusion about where the defect lives."
        )
    return (
        "If model_requests_total is still 0 at threshold 0.0 - which admits "
        "every extracted target with no filtering - then the risk gate is "
        "not the constraint and the defect is upstream of it: in "
        "diff.extract_targets, in ranking, or in the generation call. If "
        "requests rise as the threshold falls, the gate was binding and the "
        "default of 0.35 is mistuned for this repository. This condition was "
        "written before the run and must not be reinterpreted after it."
    )


def ladder_verdict(rungs: list[dict]) -> str:
    """Classify the ladder. Pure; the whole point is that it is testable.

    ``rungs`` must be descending by threshold, each carrying at least
    ``risk_threshold`` and ``model_requests_total``.
    """
    if not rungs:
        return INCONCLUSIVE
    requests = [int(rung.get("model_requests_total", 0)) for rung in rungs]
    floor = min(float(rung["risk_threshold"]) for rung in rungs)
    if all(count == 0 for count in requests):
        # Only meaningful if the bottom rung really was unfiltered.
        return UPSTREAM if floor == 0.0 else INCONCLUSIVE
    if len(requests) < 2:
        return INCONCLUSIVE
    # Loosening admitted work that the default was excluding.
    if requests[-1] > requests[0]:
        return GATE_WAS_BINDING
    # Requests happened, and loosening changed nothing. The gate was not what
    # was holding measurement back, even though measurement is still short.
    if len(set(requests)) == 1:
        return GATE_NOT_BINDING
    return INCONCLUSIVE


def verdict_note(verdict: str) -> str:
    return {
        UPSTREAM: (
            "Zero model requests even with the risk gate fully open. The "
            "threshold is exonerated. Look upstream: diff.extract_targets "
            "returning nothing, ranking dropping every target, or the "
            "generation step short-circuiting before its first POST. Do not "
            "tune risk.py on the strength of this run."
        ),
        GATE_WAS_BINDING: (
            "Requests rose as the threshold fell, so the default of 0.35 was "
            "excluding work on this repository. That is a tuning finding, "
            "not a correctness finding: a lower threshold buys coverage by "
            "spending money on lower-risk targets, and whether that trade is "
            "worth making needs a false-positive rate, which this module "
            "does not produce."
        ),
        GATE_NOT_BINDING: (
            "Requests were made and the count did not change across rungs, "
            "so the threshold is not what is capping measurement. Whatever "
            "is short of the completion floor is downstream of target "
            "selection."
        ),
        INCONCLUSIVE: (
            "The ladder does not decide the question. Check that the lowest "
            "rung is 0.0 and that at least two rungs ran to completion "
            "before reading anything into these counts."
        ),
    }[verdict]


def run_rung(
    repo: Path,
    pairs: list[tuple[str, str]],
    threshold: float,
    model: str | None,
    budget: float,
    dry_run: bool,
) -> tuple[dict, list[dict]]:
    """Run every pair at one threshold and summarise.

    Imported here rather than at module scope for the same reason
    false_positives.py does it: ci.yml runs the whole test tree once with no
    third-party packages installed at all, and a module-level import of the
    package under test turns that step red on collection.
    """
    from jittest.config import load_config
    from jittest.llm import build_llm
    from jittest.pipeline import run as run_pipeline

    rows: list[dict] = []
    for base, head in pairs:
        try:
            overrides = {
                "budget_usd": budget,
                "max_targets": 5,
                "candidates_per_target": 4,
                "risk_threshold": threshold,
            }
            if model is not None:
                overrides["model"] = model
            cfg = load_config(repo, overrides=overrides)
            llm = build_llm(
                cfg.model,
                dry_run=dry_run,
                budget_usd=cfg.budget_usd,
                temperature=cfg.temperature,
                request_ceiling=cfg.max_targets * cfg.candidates_per_target + 5,
            )
            report = run_pipeline(
                repo=repo, base=base, head=head, cfg=cfg, llm=llm
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
                "model_requests": getattr(report, "model_requests", 0),
                "diff_status": getattr(report, "diff_status", None),
                "targets_considered": getattr(
                    report, "targets_considered", None
                ),
                "candidates_generated": getattr(
                    report, "candidates_generated", None
                ),
                "python_files_changed": len(
                    changed_python_files(repo, base, head)
                ),
            })
        except Exception as exc:  # noqa: BLE001 - preserve every row
            rows.append({
                "base": base[:8],
                "head": head[:8],
                "error": f"{type(exc).__name__}: {exc}",
                "model_requests": 0,
            })
    summary = summarize_rows(rows, len(pairs))
    summary["risk_threshold"] = threshold
    return summary, rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hold the PR set fixed and vary only risk_threshold, to find out "
            "whether the risk gate is why the model is never called"
        )
    )
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--model", default=None)
    parser.add_argument("--budget", type=float, default=1.0)
    parser.add_argument("--thresholds", default=DEFAULT_THRESHOLDS)
    parser.add_argument("--out", type=Path, default=Path("fp-ladder.json"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", default=DEFAULT_SINCE)
    parser.add_argument("--until", default=DEFAULT_UNTIL)
    args = parser.parse_args()

    thresholds = parse_thresholds(args.thresholds)
    condition = refutation_condition(thresholds)
    print("REFUTATION CONDITION (fixed before the run):")
    print(condition)
    print()

    # Selected once. Re-selecting per rung would let the PR set drift between
    # rungs and turn a controlled experiment into three unrelated runs.
    pairs, screened_out = select_pairs(
        args.repo, args.count, since=args.since, until=args.until
    )
    print(
        f"{len(pairs)} eligible PRs, {screened_out} screened out as "
        f"ineligible. The same {len(pairs)} run at every rung."
    )
    if not pairs:
        print(
            "FAIL: no eligible PRs; the ladder cannot say anything about the "
            "risk gate on an empty sample"
        )
        return 1

    rungs: list[dict] = []
    detail: dict[str, list[dict]] = {}
    for threshold in thresholds:
        print(f"\n--- risk_threshold = {threshold} ---")
        summary, rows = run_rung(
            args.repo, pairs, threshold, args.model, args.budget, args.dry_run
        )
        rungs.append(summary)
        detail[str(threshold)] = rows
        print(describe(summary))

    verdict = ladder_verdict(rungs)
    print("\n=== LADDER ===")
    print(f"{'threshold':>10}  {'requests':>9}  {'measured':>9}  completion")
    for rung in rungs:
        print(
            f"{rung['risk_threshold']:>10}  "
            f"{rung['model_requests_total']:>9}  "
            f"{rung['prs_analysed']:>9}  "
            f"{rung['completion_rate']}"
        )
    print(f"\nVERDICT: {verdict}")
    print(verdict_note(verdict))

    args.out.write_text(
        json.dumps(
            {
                "refutation_condition": condition,
                "pairs_selected": len(pairs),
                "prs_screened_out_as_ineligible": screened_out,
                "thresholds": thresholds,
                "rungs": rungs,
                "verdict": verdict,
                "verdict_note": verdict_note(verdict),
                "results_by_threshold": detail,
                "NOTE": (
                    "This artifact answers one question: is the risk gate why "
                    "the model is not being called. It is not a "
                    "false-positive rate and must not be quoted as one."
                ),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if verdict != INCONCLUSIVE else 1


if __name__ == "__main__":
    raise SystemExit(main())
