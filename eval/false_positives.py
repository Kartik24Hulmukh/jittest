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

Selection heuristic: merge commits older than 90 days whose own merge subject
does not contain revert, hotfix, regression, or rollback. This does not prove
cleanliness and must not be described as doing so.

On zero findings: a run that surfaces no claims does not have a 0% false
positive rate. It has an *unknown* rate whose 95% upper bound is 3/n (the rule
of three). At n=32 that bound is 9.4%, which is consistent with a tool that is
wrong on roughly one PR in eleven. Every rate emitted by this module therefore
carries an upper bound, and the two must be quoted together. Publishing the
point estimate alone is the precision-side equivalent of writing RESULTS.md
before a sweep exists.

On collapse: withholding a rate is necessary and not sufficient. A run that
measures 3 of 32 PRs has told you nothing unless it also tells you what
happened to the other 29. The same instrument scored 32/40 on youtube-dl and
3/32 on requests; one of those is a fact about jittest and the other is a fact
about a repository, and an artifact that cannot separate them is a dead end.
Every non-result now names its dominant cause.
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

# A row that raised nothing but also called nothing. Distinct from an
# exception: the pipeline decided there was no work, which is a different
# diagnosis from the pipeline breaking.
NO_REQUESTS = "no_model_requests"


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


def failure_reasons(rows: list[dict]) -> dict[str, int]:
    """Bucket every unmeasured row by cause, highest count first.

    Exceptions are keyed by their type name only. The message usually carries
    a path, a SHA or a URL, so keying on the full string would produce one
    bucket per row and defeat the purpose.
    """
    counter: Counter[str] = Counter()
    for row in rows:
        error = row.get("error")
        if error:
            counter[str(error).split(":", 1)[0].strip() or "Exception"] += 1
        elif row.get("model_requests", 0) <= 0:
            counter[NO_REQUESTS] += 1
    return dict(counter.most_common())


def summarize_rows(rows: list[dict], attempted: int) -> dict:
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
    """
    usable = [
        row for row in rows
        if "error" not in row and row.get("model_requests", 0) > 0
    ]
    noisy = [row for row in usable if row.get("reported", 0) > 0]
    completion = len(usable) / attempted if attempted else 0.0
    gate_ready = attempted > 0 and completion >= MIN_COMPLETION_RATE
    publishable = bool(gate_ready and usable)
    bound = upper_bound_95(len(noisy), len(usable)) if publishable else None
    reasons = failure_reasons(rows)
    dominant = next(iter(reasons), None)
    return {
        "prs_attempted": attempted,
        "prs_analysed": len(usable),
        "prs_errored_or_unmeasured": attempted - len(usable),
        "model_requests_total": sum(
            int(row.get("model_requests", 0)) for row in rows
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
        "failure_reasons": reasons,
        "dominant_failure": dominant,
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
            "reporting a property of the codebases until proven otherwise."
        ),
    }


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
        return sentence
    analysed = summary["prs_analysed"]
    noisy = summary["prs_with_a_report"]
    bound = summary["false_positive_rate_upper_bound_95"]
    if noisy == 0:
        return (
            f"No false positives surfaced on {analysed} apparently uneventful "
            f"merged PRs. That bounds the false-positive rate below "
            f"{bound * 100:.1f}% at 95% confidence; it does not establish that "
            "the rate is zero."
        )
    rate = summary["false_positive_rate"]
    return (
        f"{noisy} of {analysed} apparently uneventful merged PRs surfaced a "
        f"claim: a candidate false-positive rate of {rate * 100:.1f}% "
        f"(95% upper bound {bound * 100:.1f}%). Each claim requires blind "
        "adjudication before it counts as a false positive."
    )


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
    args = parser.parse_args()

    from jittest.config import load_config
    from jittest.llm import build_llm
    from jittest.pipeline import run as run_pipeline

    pairs = clean_merges(args.repo, args.count)
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
                "model_requests": getattr(report, "model_requests", 0),
                "diff_status": getattr(report, "diff_status", None),
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

    summary = summarize_rows(rows, len(pairs))
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
    return 0


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        errors="replace",
    ).stdout


def clean_merges(repo: Path, count: int) -> list[tuple[str, str]]:
    """Return (base_sha, head_sha) pairs for apparently uneventful merges."""
    log = git(
        repo,
        "log",
        "--merges",
        "--since=2.years",
        "--until=90.days",
        "--pretty=%H%x00%P%x00%s",
    ).strip().splitlines()
    pairs: list[tuple[str, str]] = []
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
        pairs.append((parent_shas[0], parent_shas[1]))
        if len(pairs) >= count:
            break
    return pairs


if __name__ == "__main__":
    raise SystemExit(main())
