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
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

MIN_COMPLETION_RATE = 0.80
SUSPECT = re.compile(r"\b(revert|hotfix|regression|rollback)\b", re.I)


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


def summarize_rows(rows: list[dict], attempted: int) -> dict:
    """Withhold the rate when coverage is too low to support it.

    An earlier version divided by ``max(len(usable), 1)``. Zero work therefore
    printed 0.0% false positives and exited successfully. This function makes
    insufficient evidence an explicit terminal state instead.
    """
    usable = [
        row for row in rows
        if "error" not in row and row.get("model_requests", 0) > 0
    ]
    noisy = [row for row in usable if row.get("reported", 0) > 0]
    completion = len(usable) / attempted if attempted else 0.0
    gate_ready = attempted > 0 and completion >= MIN_COMPLETION_RATE
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
            round(len(noisy) / len(usable), 3)
            if gate_ready and usable else None
        ),
        "comments_per_100_prs": (
            round(100 * len(noisy) / len(usable), 1)
            if gate_ready and usable else None
        ),
        "gate_ready": gate_ready,
        "NOTE": (
            "Rate is withheld unless at least 80% of selected PRs produced "
            "measured results. Every surfaced claim still requires blind human "
            "adjudication; an uneventful merge is not known-clean ground truth."
        ),
    }


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
    if not summary["gate_ready"]:
        print(
            "FAIL: insufficient measured PRs; refusing to publish a "
            "false-positive rate"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
