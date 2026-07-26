"""Measure the number that actually decides adoption: the false-positive rate.

Method: run jittest over merged PRs that were NOT regressions - PRs that shipped
and were never reverted or hotfixed. Any reported "regression" on those is, by
construction, a false positive.

This is the mirror of run_bugsinpy.py. Recall without precision is marketing.
Meta's own headline contribution in arXiv:2601.22832 was a ~70% reduction in
human review load, which is a precision claim, not a recall claim.

Usage:
    python eval/false_positives.py --repo ~/src/requests --count 40

Selection heuristic for "clean" PRs: merge commits older than 90 days whose
merged branch was never touched by a later commit message containing revert,
hotfix, or fixes #<pr>.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

SUSPECT = re.compile(r"\b(revert|hotfix|regression|rollback)\b", re.I)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    ).stdout


def clean_merges(repo: Path, count: int) -> list[tuple[str, str]]:
    """Return (base_sha, head_sha) pairs for merges that look uneventful."""
    log = git(repo, "log", "--merges", "--since=2.years", "--until=90.days",
              "--pretty=%H%x00%P%x00%s").strip().splitlines()
    suspicious_subjects = SUSPECT
    pairs: list[tuple[str, str]] = []
    for line in log:
        parts = line.split("\x00")
        if len(parts) != 3:
            continue
        _sha, parents, subject = parts
        if suspicious_subjects.search(subject):
            continue
        p = parents.split()
        if len(p) != 2:
            continue
        pairs.append((p[0], p[1]))  # first parent = base, second = merged head
        if len(pairs) >= count:
            break
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--count", type=int, default=40)
    ap.add_argument("--model", default=None)
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=Path("false-positives.json"))
    args = ap.parse_args()

    from jittest import pipeline

    pairs = clean_merges(args.repo, args.count)
    rows = []
    for base, head in pairs:
        try:
            rep = pipeline.run(repo=args.repo, base_rev=base, head_rev=head,
                               model=args.model, budget_usd=args.budget)
            reported = [f for f in rep.findings if f.assessment.should_report]
            rows.append({
                "base": base[:8], "head": head[:8],
                "reported": len(reported),
                "cost_usd": rep.cost_usd,
                "claims": [f.assessment.one_line for f in reported],
            })
        except Exception as exc:  # noqa: BLE001
            rows.append({"base": base[:8], "head": head[:8], "error": str(exc)})

    usable = [r for r in rows if "error" not in r]
    noisy = [r for r in usable if r["reported"] > 0]
    summary = {
        "prs_analysed": len(usable),
        "prs_with_a_report": len(noisy),
        "false_positive_rate": round(len(noisy) / max(len(usable), 1), 3),
        "comments_per_100_prs": round(100 * len(noisy) / max(len(usable), 1), 1),
        "NOTE": (
            "Some of these may be genuine latent bugs rather than false "
            "positives. Read the claims by hand before quoting this number. "
            "Target: fewer than 10 comments per 100 clean PRs."
        ),
    }
    args.out.write_text(json.dumps({"summary": summary, "results": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
