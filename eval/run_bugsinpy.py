"""Evaluate jittest against BugsInPy by inverting each fix into a regression.

BugsInPy (soarsmu/BugsInPy) ships 493 real Python bugs, each with a buggy
commit, a fixed commit, and the developer test that triggers the bug.

The inversion trick:

    base = fixed commit    (correct behaviour)
    head = buggy commit    (the synthetic "regression PR")

A perfect jittest run produces a test that PASSES on base and FAILS on head.
Because BugsInPy ships the ground-truth triggering test, catch rate is
measurable exactly rather than estimated.

Usage:
    git clone https://github.com/soarsmu/BugsInPy /tmp/BugsInPy
    python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --limit 50 --out results.json

HONESTY RULE: never publish catch rate without false-positive rate and cost.
Also report GitBug-Java or another recent-bug set alongside, because BugsInPy
is in public training corpora and memorisation inflates results.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class BugSpec:
    project: str
    bug_id: str
    repo_url: str
    buggy_commit: str
    fixed_commit: str
    test_file: str = ""


@dataclass
class BugResult:
    project: str
    bug_id: str
    caught: bool = False
    candidates: int = 0
    mechanically_catching: int = 0
    reported: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str = ""
    reasons: list[str] = field(default_factory=list)


def discover(bugsinpy: Path, limit: int | None) -> list[BugSpec]:
    """Walk projects/<name>/bugs/<id>/bug.info and parse the commit pair."""
    specs: list[BugSpec] = []
    projects = sorted((bugsinpy / "projects").iterdir())
    for project in projects:
        info_root = project / "bugs"
        if not info_root.is_dir():
            continue
        repo_url = ""
        pj = project / "project.info"
        if pj.exists():
            for line in pj.read_text(errors="replace").splitlines():
                if line.startswith("github_url"):
                    repo_url = line.split("=", 1)[1].strip().strip('"')
        for bug_dir in sorted(info_root.iterdir()):
            info = bug_dir / "bug.info"
            if not info.exists():
                continue
            fields: dict[str, str] = {}
            for line in info.read_text(errors="replace").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    fields[k.strip()] = v.strip().strip('"')
            specs.append(
                BugSpec(
                    project=project.name,
                    bug_id=bug_dir.name,
                    repo_url=repo_url,
                    buggy_commit=fields.get("buggy_commit_id", ""),
                    fixed_commit=fields.get("fixed_commit_id", ""),
                    test_file=fields.get("test_file", ""),
                )
            )
            if limit and len(specs) >= limit:
                return specs
    return specs


def clone(spec: BugSpec, workdir: Path) -> Path | None:
    dest = workdir / f"{spec.project}"
    if dest.exists():
        return dest
    if not spec.repo_url:
        return None
    r = subprocess.run(
        ["git", "clone", "--quiet", spec.repo_url, str(dest)],
        capture_output=True, text=True,
    )
    return dest if r.returncode == 0 else None


def evaluate_one(spec: BugSpec, repo: Path, model: str, budget: float) -> BugResult:
    from jittest import pipeline

    res = BugResult(project=spec.project, bug_id=spec.bug_id)
    t0 = time.time()
    try:
        report = pipeline.run(
            repo=repo,
            base_rev=spec.fixed_commit,   # correct behaviour
            head_rev=spec.buggy_commit,   # the synthetic regression
            model=model,
            budget_usd=budget,
        )
        res.candidates = report.candidates_generated
        res.mechanically_catching = report.mechanically_catching
        res.reported = len([f for f in report.findings if f.assessment.should_report])
        res.cost_usd = report.cost_usd
        res.caught = res.reported > 0
        res.reasons = [f.assessment.one_line for f in report.findings]
    except Exception as exc:  # noqa: BLE001 - eval harness must not die on one bug
        res.error = f"{type(exc).__name__}: {exc}"
    res.seconds = round(time.time() - t0, 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bugsinpy", type=Path, required=True)
    ap.add_argument("--workdir", type=Path, default=Path("/tmp/jittest-eval"))
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--model", default=None)
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=Path("eval-results.json"))
    args = ap.parse_args()

    args.workdir.mkdir(parents=True, exist_ok=True)
    specs = discover(args.bugsinpy, args.limit)
    print(f"Discovered {len(specs)} bugs", file=sys.stderr)

    results: list[BugResult] = []
    for i, spec in enumerate(specs, 1):
        repo = clone(spec, args.workdir)
        if repo is None:
            results.append(BugResult(spec.project, spec.bug_id, error="clone failed"))
            continue
        r = evaluate_one(spec, repo, args.model, args.budget)
        results.append(r)
        print(f"[{i}/{len(specs)}] {spec.project}-{spec.bug_id} "
              f"caught={r.caught} cost=${r.cost_usd:.2f} {r.error}", file=sys.stderr)

    usable = [r for r in results if not r.error]
    summary = {
        "bugs_attempted": len(results),
        "bugs_usable": len(usable),
        "catch_rate": round(sum(r.caught for r in usable) / max(len(usable), 1), 3),
        "mean_candidates": round(statistics.fmean([r.candidates for r in usable] or [0]), 1),
        "mechanical_yield": round(
            sum(r.mechanically_catching for r in usable)
            / max(sum(r.candidates for r in usable), 1), 3
        ),
        "mean_cost_usd": round(statistics.fmean([r.cost_usd for r in usable] or [0]), 3),
        "mean_seconds": round(statistics.fmean([r.seconds for r in usable] or [0]), 1),
        "NOTE": (
            "catch_rate here is recall on seeded real bugs. It is NOT the "
            "headline number on its own. Pair it with the false-positive rate "
            "from eval/false_positives.py before publishing anything."
        ),
    }
    args.out.write_text(json.dumps(
        {"summary": summary, "results": [asdict(r) for r in results]}, indent=2
    ))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
