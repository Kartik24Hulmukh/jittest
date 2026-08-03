"""Make `below_risk_threshold` a number instead of a bucket.

The dominant unmeasured cause on the flask corpus is `below_risk_threshold`:
18 of 28 unmeasured pull requests in the Session V false-positive run, and 8 of
15 in the funnel re-run. That bucket currently records only that every target
scored under the cutoff. It does not record *what* they scored, so there is no
way to tell three very different situations apart:

1. The ranker is working and those pull requests genuinely are low risk.
2. The cutoff is slightly too high and the mass sits just underneath it.
3. Something upstream is starving the score - empty `source_after`, every
   target reported as a new symbol, or a diff that never reached the file the
   change actually lives in.

Telling those apart is the difference between tuning a constant and finding a
defect, and it is not a question anyone should answer by adjusting the
threshold until the numbers improve.

This module changes no behaviour and no threshold. It reads a revision range,
scores every extracted target with the shipped `score_target`, and prints the
distribution. It calls no model, needs no API key and touches no network, so it
can be run on any repository at zero cost and rerun by anyone checking the
result.

Usage:

    python eval/rank_calibration.py --repo /path/to/clone --base <rev> --head <rev>
    python eval/rank_calibration.py --repo . --base origin/main --head HEAD --json

Exit codes: 0 the range was scored, 2 the range could not be scored.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jittest.diff import GitError, extract_targets, git_diff  # noqa: E402
from jittest.risk import rank, score_target  # noqa: E402

DEFAULT_THRESHOLD = 0.35
BUCKET_WIDTH = 0.05


def _bucket(score: float) -> str:
    low = int(score / BUCKET_WIDTH) * BUCKET_WIDTH
    return f"{low:.2f}-{low + BUCKET_WIDTH:.2f}"


def calibrate(repo: Path, base: str, head: str, threshold: float) -> dict:
    diff_text = git_diff(repo, base, head)
    targets = extract_targets(diff_text, repo=repo, base=base, head=head)
    if not targets:
        return {
            "base": base,
            "head": head,
            "targets_extracted": 0,
            "verdict": "no_targets_extracted",
            "note": "nothing was scored, so this range says nothing about the threshold",
        }

    scored = sorted((score_target(t) for t in targets), key=lambda s: -s.score)
    values = [s.score for s in scored]
    passing = [s for s in scored if s.score >= threshold]

    histogram: dict[str, int] = {}
    for value in values:
        key = _bucket(value)
        histogram[key] = histogram.get(key, 0) + 1

    # How much of the shortfall sits just under the cutoff. If most rejected
    # targets are within one bucket of it, the cutoff is the live question. If
    # they are at the floor, the cutoff is not the problem and lowering it would
    # only buy noise.
    near_miss = sum(1 for v in values if threshold - BUCKET_WIDTH <= v < threshold)
    at_floor = sum(1 for v in values if v < 0.10)

    # Upstream starvation indicators. These are the reasons a real change can
    # score like an empty one.
    module_level = sum(1 for t in targets if t.symbol == "<module>")
    no_prior_source = sum(1 for t in targets if not t.modifies_existing)
    halved = sum(1 for t in targets if t.churn <= 2 and not t.modifies_existing)

    if passing:
        verdict = "threshold_reachable"
    elif near_miss:
        verdict = "all_below_but_clustered_at_the_cutoff"
    elif at_floor == len(values):
        verdict = "all_at_the_floor_suspect_upstream"
    else:
        verdict = "all_below_threshold"

    return {
        "base": base,
        "head": head,
        "threshold": threshold,
        "targets_extracted": len(targets),
        "targets_at_or_above_threshold": len(passing),
        "share_at_or_above_threshold": round(len(passing) / len(values), 4),
        "ranked_returned": len(rank(targets, threshold=threshold)),
        "max": max(values),
        "median": round(statistics.median(values), 4),
        "min": min(values),
        "near_miss_within_one_bucket": near_miss,
        "at_floor_below_0.10": at_floor,
        "module_level_targets": module_level,
        "targets_with_no_prior_source": no_prior_source,
        "targets_halved_by_new_small_symbol_penalty": halved,
        "histogram": dict(sorted(histogram.items())),
        "verdict": verdict,
        "top": [
            {"symbol": s.target.qualified, "score": s.score, "reasons": s.reasons}
            for s in scored[:10]
        ],
    }


def _render(report: dict) -> str:
    if not report.get("targets_extracted"):
        return f"no targets extracted for {report['base']}..{report['head']}"
    lines = [
        f"range        {report['base']}..{report['head']}",
        f"targets      {report['targets_extracted']}",
        f"at or above  {report['targets_at_or_above_threshold']}"
        f"  ({report['share_at_or_above_threshold']:.1%} of targets,"
        f" threshold {report['threshold']})",
        f"spread       min {report['min']}  median {report['median']}  max {report['max']}",
        f"near miss    {report['near_miss_within_one_bucket']}"
        f"   at floor {report['at_floor_below_0.10']}",
        f"upstream     module-level {report['module_level_targets']},"
        f" no prior source {report['targets_with_no_prior_source']},"
        f" halved {report['targets_halved_by_new_small_symbol_penalty']}",
        f"verdict      {report['verdict']}",
        "",
        "histogram",
    ]
    for key, count in report["histogram"].items():
        lines.append(f"  {key}  {'#' * min(count, 60)} {count}")
    lines.append("")
    lines.append("highest scoring targets")
    for row in report["top"]:
        lines.append(f"  {row['score']:.4f}  {row['symbol']}  {', '.join(row['reasons'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = calibrate(Path(args.repo), args.base, args.head, args.threshold)
    except GitError as exc:
        print(f"could not score this range: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2) if args.json else _render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
