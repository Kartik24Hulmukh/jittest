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

    # Dry run (no network, no key, no cost):
    python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --limit 5 --dry-run

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
    status: str = "pending"  # pending, caught, missed, not_measured, skipped, error
    candidates: int = 0
    catching_candidates: int = 0
    reported: int = 0
    cost_usd: float = 0.0
    priced: bool = True
    seconds: float = 0.0
    error: str = ""
    telemetry: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def discover(bugsinpy: Path, limit: int | None,
             project_filter: list[str] | None = None) -> list[BugSpec]:
    """Walk projects/<name>/bugs/<id>/bug.info and parse the commit pair."""
    specs: list[BugSpec] = []
    projects_dir = bugsinpy / "projects"
    if not projects_dir.is_dir():
        return specs
    projects = sorted(projects_dir.iterdir())
    for project in projects:
        if project_filter and project.name not in project_filter:
            continue
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


def evaluate_one(spec: BugSpec, repo: Path, model: str, budget: float,
                 dry_run: bool = False) -> BugResult:
    """Run the jittest pipeline against a single BugsInPy bug.

    Uses the INVERTED setup: base = fixed commit, head = buggy commit.
    """
    from jittest.config import load_config
    from jittest.llm import build_llm
    from jittest.pipeline import run as run_pipeline

    res = BugResult(project=spec.project, bug_id=spec.bug_id)
    t0 = time.time()

    if not spec.buggy_commit or not spec.fixed_commit:
        res.status = "skipped"
        res.error = "missing commit IDs in bug.info"
        res.seconds = round(time.time() - t0, 1)
        return res

    try:
        # Use load_config so JITTEST_MODEL and JITTEST_API_BASE from the
        # environment are respected. The previous code created Config
        # directly, which ignored env vars and hardcoded the model.
        from jittest.config import load_config
        cfg = load_config(repo, overrides={
            "model": model,
            "budget_usd": budget,
            "max_targets": 5,
            "candidates_per_target": 4,
            "risk_threshold": 0.35,
        })

        # Fail-fast guard: if an API key is present but dry-run was selected,
        # refuse to report an unmeasured result.
        import os as _os
        has_key = bool(_os.getenv("JITTEST_API_KEY"))
        if has_key and dry_run:
            res.status = "error"
            res.error = "api key present but dry-run selected: refusing to report an unmeasured result"
            res.seconds = round(time.time() - t0, 1)
            return res

        llm = build_llm(cfg.model, dry_run=dry_run, budget_usd=cfg.budget_usd,
                        temperature=cfg.temperature)
        report = run_pipeline(
            repo=repo,
            base=spec.fixed_commit,
            head=spec.buggy_commit,
            cfg=cfg,
            llm=llm,
        )
        res.candidates = report.candidates_generated
        res.catching_candidates = len(report.findings)
        res.reported = len([f for f in report.findings if f.assessment.should_report])
        res.cost_usd = report.cost_usd
        res.priced = report.priced
        res.caught = res.reported > 0
        # A bug with zero candidates AND zero elapsed model time was not measured,
        # not missed. Reporting it as "missed" with catch_rate 0.0 is a false
        # statement about the product.
        elapsed = round(time.time() - t0, 1)
        if res.candidates == 0 and elapsed == 0.0:
            res.status = "not_measured"
        else:
            res.status = "caught" if res.reported > 0 else "missed"
        res.reasons = [f.assessment.summary for f in report.findings]
        res.telemetry = [t.as_dict() for t in report.telemetry]
    except Exception as exc:  # noqa: BLE001 - eval harness must not die on one bug
        res.status = "error"
        res.error = f"{type(exc).__name__}: {exc}"
    res.seconds = round(time.time() - t0, 1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Evaluate jittest against BugsInPy (inverted setup)")
    ap.add_argument("--bugsinpy", type=Path, required=True,
                    help="Path to a local clone of soarsmu/BugsInPy")
    ap.add_argument("--workdir", type=Path, default=Path("/tmp/jittest-eval"))
    ap.add_argument("--limit", type=int, default=50,
                    help="Maximum number of bugs to evaluate")
    ap.add_argument("--model", default=None,
                    help="Model identifier (default: from config)")
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=Path("eval-results.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="Run with a stub model: no network, no key, no cost")
    ap.add_argument("--project", action="append", default=None,
                    help="Filter to specific projects (repeatable)")
    args = ap.parse_args()

    args.workdir.mkdir(parents=True, exist_ok=True)
    specs = discover(args.bugsinpy, args.limit, args.project)
    print(f"Discovered {len(specs)} bugs", file=sys.stderr)

    results: list[BugResult] = []
    for i, spec in enumerate(specs, 1):
        repo = clone(spec, args.workdir)
        if repo is None:
            r = BugResult(spec.project, spec.bug_id,
                          status="skipped", error="clone failed")
            results.append(r)
            print(f"[{i}/{len(specs)}] {spec.project}-{spec.bug_id} "
                  f"SKIPPED: clone failed", file=sys.stderr)
            continue
        r = evaluate_one(spec, repo, args.model, args.budget, args.dry_run)
        results.append(r)
        print(f"[{i}/{len(specs)}] {spec.project}-{spec.bug_id} "
              f"status={r.status} candidates={r.candidates} "
              f"catching={r.catching_candidates} reported={r.reported} "
              f"cost={'unpriced' if not r.priced else f'${r.cost_usd:.3f}'} "
              f"{r.error}", file=sys.stderr)

    usable = [r for r in results if r.status not in ("error", "skipped", "not_measured")]
    caught = [r for r in usable if r.status == "caught"]
    measured_count = len(usable)
    summary = {
        "bugs_attempted": len(results),
        "bugs_measured": measured_count,
        "bugs_not_measured": len([r for r in results if r.status == "not_measured"]),
        "bugs_skipped": len([r for r in results if r.status == "skipped"]),
        "bugs_errored": len([r for r in results if r.status == "error"]),
        "catch_rate": round(len(caught) / max(measured_count, 1), 3) if measured_count > 0 else None,
        "mean_candidates": round(
            statistics.fmean([r.candidates for r in usable] or [0]), 1),
        "oracle_yield": round(
            sum(r.catching_candidates for r in usable)
            / max(sum(r.candidates for r in usable), 1), 3),
        "mean_cost_usd": round(
            statistics.fmean([r.cost_usd for r in usable] or [0]), 3),
        "priced": all(r.priced for r in usable) if usable else True,
        "mean_seconds": round(
            statistics.fmean([r.seconds for r in usable] or [0]), 1),
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
