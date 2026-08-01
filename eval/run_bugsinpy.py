"""Evaluate jittest against BugsInPy by inverting each fix into a regression.

BugsInPy (soarsmu/BugsInPy) ships 493 real Python bugs, each with a buggy
commit, a fixed commit, and the developer test that triggers the bug.

The inversion trick:

    base = fixed commit    (correct behaviour)
    head = buggy commit    (the synthetic "regression PR")

A perfect jittest run produces a test that PASSES on base and FAILS on head.
BugsInPy supplies known buggy/fixed revision pairs. The harness measures whether
jittest mechanically produces a pass-on-fixed/fail-on-buggy catching test. The
benchmark trigger metadata is retained for provenance; it is not used as a
self-grading oracle, so results must not be described as exact semantic matches.

Usage:
    git clone https://github.com/soarsmu/BugsInPy /tmp/BugsInPy
    python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --limit 50 --out results.json

    # Dry run (no network, no key, no cost):
    python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --limit 5 --dry-run

HONESTY RULE: never publish catch rate without false-positive rate and cost.
Also report GitBug-Java or another recent-bug set alongside, because BugsInPy
is in public training corpora and memorisation inflates results.

ENVIRONMENT RULE (defect 69): a candidate that cannot be imported was never
given the chance to catch anything. Before measuring, this harness makes real
pytest importable and installs the dependencies of the project under test. A
run in which those steps failed is reported as such per bug, because the
alternative - a clean-looking catch_rate of 0.0 - is a false statement about
the tool.
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

PIP_TIMEOUT_SECONDS = 900


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
    status: str = "pending"  # pending, caught, missed, not_measured,
                             # git_failed, skipped, error
    candidates: int = 0
    catching_candidates: int = 0
    reported: int = 0
    cost_usd: float = 0.0
    priced: bool = True
    model_requests: int = 0
    seconds: float = 0.0
    error: str = ""
    # Defect 69. Whether the runner could actually import pytest and the
    # dependencies of the project under test. Without this, a run in which
    # nothing could be collected is indistinguishable from a run in which the
    # model simply failed.
    runner: str = "unknown"
    deps_status: str = "unknown"
    deps_error: str = ""
    telemetry: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


_pytest_state: dict[str, str] = {}
_deps_cache: dict[str, tuple[str, str]] = {}


def ensure_pytest() -> str:
    """Make real pytest importable, once per process. Defect 69.

    jittest declares no runtime dependencies on purpose, and the eval workflow
    installs jittest alone. detect_runner() therefore probed `import pytest`,
    failed, and fell back to the vendored minirunner shim for every candidate
    in run 30655481944. The shim exists so that jittest works in a repository
    that does not have pytest; it is not the environment a benchmark should
    measure the tool in, because a shim-surface gap is then indistinguishable
    from a generation failure.

    Returns one of: already-present, installed, install-failed.
    """
    if "result" in _pytest_state:
        return _pytest_state["result"]
    probe = subprocess.run(
        [sys.executable, "-c", "import pytest"],
        capture_output=True, text=True, errors="replace",
    )
    if probe.returncode == 0:
        _pytest_state["result"] = "already-present"
        return _pytest_state["result"]
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "pytest"],
            capture_output=True, text=True, errors="replace",
            timeout=PIP_TIMEOUT_SECONDS,
        )
        ok = r.returncode == 0
    except subprocess.TimeoutExpired:
        ok = False
    _pytest_state["result"] = "installed" if ok else "install-failed"
    return _pytest_state["result"]


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
        capture_output=True, text=True, errors="replace",
    )
    return dest if r.returncode == 0 else None


def requirements_for(spec: BugSpec, bugsinpy: Path, repo: Path) -> Path | None:
    """Locate a requirements file for this bug, most specific first.

    BugsInPy ships per-bug requirements under projects/<name>/bugs/<id>/.
    Fall back to the project level, then to the cloned repository itself.
    """
    candidates = [
        bugsinpy / "projects" / spec.project / "bugs" / spec.bug_id / "requirements.txt",
        bugsinpy / "projects" / spec.project / "requirements.txt",
        repo / "requirements.txt",
    ]
    for path in candidates:
        try:
            if path.is_file() and path.read_text(errors="replace").strip():
                return path
        except OSError:
            continue
    return None


def install_project_deps(spec: BugSpec, bugsinpy: Path,
                         repo: Path) -> tuple[str, str]:
    """Install the dependencies of the project under test. Defect 69.

    clone() used to clone and stop. execute._env_for() puts the worktree on
    PYTHONPATH, so the project's own modules import fine - but nothing its
    tests import does. In run 30655481944 that produced 20 head_uncollectable
    candidates out of 30 and zero base/head execution pairs.

    Cached per project. Returns (status, detail) where status is one of:
    installed, no-requirements, install-failed, skipped-dry-run.
    """
    if spec.project in _deps_cache:
        return _deps_cache[spec.project]

    req = requirements_for(spec, bugsinpy, repo)
    if req is None:
        result = ("no-requirements", "")
        _deps_cache[spec.project] = result
        return result

    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "-r", str(req)],
            capture_output=True, text=True, errors="replace",
            timeout=PIP_TIMEOUT_SECONDS,
        )
        if r.returncode == 0:
            result = ("installed", str(req))
        else:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            result = ("install-failed", chr(10).join(tail[-6:]))
    except subprocess.TimeoutExpired:
        result = ("install-failed",
                  f"pip exceeded {PIP_TIMEOUT_SECONDS}s on {req}")

    _deps_cache[spec.project] = result
    return result


def classify(model_requests: int, catching_candidates: int,
             diff_status: str = "ok") -> str:
    """Status for one bug.

    A git failure is checked FIRST and is its own status. When git cannot
    compare the revisions, the bug was never presented to the tool: that is a
    failure to measure, not a miss. It is also not the same thing as an empty
    diff (a property of the revision pair, which stays "not_measured" and in
    the headline denominator). Lumping the two together is how a broken
    checkout once read as evidence about the model.

    Measurement is otherwise defined by whether the model was asked, never by
    elapsed time. The previous version keyed "not_measured" on a wall-clock
    value rounded to one decimal place, which meant the same unmeasured bug
    became "missed" on a slower runner and was then averaged into
    catch_rate 0.0. A tool that reports a catch rate for a run in which it
    never called a model is making a false claim about itself.

    "caught" is a mechanical statement: the differential oracle produced at
    least one test that passes on the fixed revision and fails on the buggy
    one. It deliberately does not consult the assessor, and it does not
    assert that the test is semantically equivalent to the benchmark's own
    trigger test.
    """
    if diff_status == "git_failed":
        return "git_failed"
    if model_requests <= 0:
        return "not_measured"
    return "caught" if catching_candidates > 0 else "missed"


def environment_warnings(results: list[BugResult]) -> list[str]:
    """Name environment failures that would otherwise read as model failures.

    Defect 69. A reader seeing catch_rate 0.0 must be told, in the same
    document, whether the candidates could be imported at all.
    """
    warnings: list[str] = []
    if any(r.runner == "minirunner-shim" for r in results):
        warnings.append(
            "pytest was not importable: candidates ran under the vendored "
            "minirunner shim, whose surface is narrower than pytest. A shim "
            "gap is not a generation failure."
        )
    failed = sorted({r.project for r in results if r.deps_status == "install-failed"})
    if failed:
        warnings.append(
            "dependencies of the project under test failed to install for: "
            + ", ".join(failed)
            + ". Candidates importing them cannot be collected, and the "
            "resulting misses are environment artefacts."
        )
    uncollectable = sum(
        1
        for r in results
        for t in r.telemetry
        if t.get("disposition") == "head_uncollectable"
    )
    total = sum(len(r.telemetry) for r in results)
    if total and uncollectable / total > 0.25:
        warnings.append(
            f"{uncollectable}/{total} candidates were head_uncollectable "
            "(over 25%). The differential oracle was rarely exercised, so "
            "this run measures the environment more than the tool."
        )
    return warnings


def summarize(results: list[BugResult]) -> dict:
    """Build a failure-inclusive summary.

    The headline denominator is every ELIGIBLE bug: attempted minus
    git-failed. A git failure means the bug was never presented to the tool,
    so counting it as an attempt would be as false as counting it as a miss.
    Git failures are never silent: they are counted under their own name, and
    the conservative all-attempted rate is published beside the headline so
    the harsher number is always reconstructable. One success beside many
    broken checkouts still cannot become 100%: assert_measured.py fails any
    run whose completion rate falls below the evidence floor, which is where
    systemic collection failure is caught.
    """
    attempted = len(results)
    git_failed = [r for r in results if r.status == "git_failed"]
    eligible = attempted - len(git_failed)
    measured = [r for r in results if r.status in ("caught", "missed")]
    caught = [r for r in measured if r.status == "caught"]
    reported = [r for r in results if r.reported > 0]
    candidates = sum(r.candidates for r in measured)
    priced_rows = [r for r in measured if r.priced]
    dispositions: dict[str, int] = {}
    for r in results:
        for t in r.telemetry:
            key = str(t.get("disposition", "unknown"))
            dispositions[key] = dispositions.get(key, 0) + 1
    return {
        "bugs_attempted": attempted,
        "bugs_eligible": eligible,
        "bugs_measured": len(measured),
        "bugs_not_measured": sum(r.status == "not_measured" for r in results),
        "bugs_git_failed": len(git_failed),
        "bugs_skipped": sum(r.status == "skipped" for r in results),
        "bugs_errored": sum(r.status == "error" for r in results),
        "model_requests_total": sum(r.model_requests for r in results),
        "completion_rate": round(len(measured) / attempted, 3) if attempted else None,
        "catch_rate": round(len(caught) / eligible, 3) if eligible else None,
        "catch_rate_all_attempted": (
            round(len(caught) / attempted, 3) if attempted else None
        ),
        "conditional_catch_rate": (
            round(len(caught) / len(measured), 3) if measured else None
        ),
        "reported_rate": round(len(reported) / attempted, 3) if attempted else None,
        "mean_candidates": (
            round(statistics.fmean([r.candidates for r in measured]), 1)
            if measured else None
        ),
        "oracle_yield": (
            round(sum(r.catching_candidates for r in measured) / candidates, 3)
            if candidates else None
        ),
        "mean_cost_usd": (
            round(statistics.fmean([r.cost_usd for r in priced_rows]), 3)
            if priced_rows else None
        ),
        "priced": bool(measured) and len(priced_rows) == len(measured),
        "mean_seconds": (
            round(statistics.fmean([r.seconds for r in measured]), 1)
            if measured else None
        ),
        # Defect 69. Published beside the rate, never below it.
        "candidate_dispositions": dispositions,
        "runner": sorted({r.runner for r in results}),
        "environment_warnings": environment_warnings(results),
        "rate_definition": (
            "catch_rate = bugs with >=1 mechanical pass-on-fixed/fail-on-buggy "
            "test / eligible bugs (attempted minus git-failed, which were "
            "never presented to the tool)"
        ),
        "NOTE": (
            "catch_rate excludes git-failed runs from its denominator; "
            "catch_rate_all_attempted keeps them and is the conservative floor. "
            "Git failures are counted by name above and bounded by the "
            "completion gate, so they cannot silently raise the rate. "
            "conditional_catch_rate is diagnostic only. Read "
            "candidate_dispositions and environment_warnings before reading "
            "any rate: a candidate that could not be collected was never given "
            "the chance to catch anything, and a low rate driven by "
            "head_uncollectable is a statement about the runner, not the tool. "
            "Pair with independently adjudicated precision evidence before "
            "publication."
        ),
    }


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
        overrides = {
            "budget_usd": budget,
            "max_targets": 5,
            "candidates_per_target": 4,
            "risk_threshold": 0.35,
        }
        if model is not None:
            overrides["model"] = model
        cfg = load_config(repo, overrides=overrides)

        # Fail-fast guard: if an API key is present but dry-run was selected,
        # refuse to report an unmeasured result.
        import os as _os
        has_key = bool(_os.getenv("JITTEST_API_KEY"))
        if has_key and dry_run:
            res.status = "error"
            res.error = (
                "api key present but dry-run selected: refusing to report an "
                "unmeasured result"
            )
            res.seconds = round(time.time() - t0, 1)
            return res

        llm = build_llm(
            cfg.model,
            dry_run=dry_run,
            budget_usd=cfg.budget_usd,
            temperature=cfg.temperature,
            request_ceiling=cfg.max_targets * cfg.candidates_per_target + 5,
        )
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
        res.model_requests = getattr(report, "model_requests", 0)
        # Loop 7 added Report.diff_status; without reading it, a git failure
        # collapses into "not_measured" and sits in the catch-rate denominator
        # as if the tool had been given its chance and failed.
        res.status = classify(res.model_requests, res.catching_candidates,
                              getattr(report, "diff_status", "ok"))
        if res.status in ("not_measured", "git_failed") and report.errors \
                and not res.error:
            res.error = report.errors[0]
        res.reasons = [f.assessment.summary for f in report.findings]
        res.telemetry = [t.as_dict() for t in report.telemetry]
        res.seconds = round(time.time() - t0, 1)
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
    ap.add_argument("--skip-env-setup", action="store_true",
                    help="Do not install pytest or project requirements. "
                         "Reproduces the pre-defect-69 environment; any "
                         "resulting catch rate measures the runner.")
    args = ap.parse_args()

    setup_env = not (args.dry_run or args.skip_env_setup)

    # Defect 69. Establish the execution environment BEFORE measuring, and
    # print what it is, so the log answers "could these candidates even run?"
    if setup_env:
        pytest_status = ensure_pytest()
    else:
        pytest_status = "skipped"
    runner = "pytest" if pytest_status in ("already-present", "installed") \
        else "minirunner-shim"
    print(f"environment: pytest={pytest_status} runner={runner}", file=sys.stderr)
    if runner == "minirunner-shim":
        print("warning: pytest is not importable. Candidates will run under "
              "the vendored minirunner shim, whose surface is narrower than "
              "pytest. Collection failures in this configuration are not "
              "evidence about the model.", file=sys.stderr)

    args.workdir.mkdir(parents=True, exist_ok=True)
    specs = discover(args.bugsinpy, args.limit, args.project)
    print(f"Discovered {len(specs)} bugs", file=sys.stderr)

    results: list[BugResult] = []
    for i, spec in enumerate(specs, 1):
        repo = clone(spec, args.workdir)
        if repo is None:
            r = BugResult(spec.project, spec.bug_id,
                          status="skipped", error="clone failed")
            r.runner = runner
            r.deps_status = "not-attempted"
            results.append(r)
            print(f"[{i}/{len(specs)}] {spec.project}-{spec.bug_id} "
                  f"SKIPPED: clone failed", file=sys.stderr)
            continue

        if setup_env:
            deps_status, deps_detail = install_project_deps(
                spec, args.bugsinpy, repo)
        else:
            deps_status, deps_detail = "skipped-env-setup", ""
        if deps_status == "install-failed":
            print(f"  warning: dependency install failed for {spec.project}: "
                  f"{deps_detail}", file=sys.stderr)

        r = evaluate_one(spec, repo, args.model, args.budget, args.dry_run)
        r.runner = runner
        r.deps_status = deps_status
        r.deps_error = deps_detail if deps_status == "install-failed" else ""
        results.append(r)
        print(f"[{i}/{len(specs)}] {spec.project}-{spec.bug_id} "
              f"status={r.status} candidates={r.candidates} "
              f"catching={r.catching_candidates} reported={r.reported} "
              f"deps={r.deps_status} "
              f"cost={'unpriced' if not r.priced else f'${r.cost_usd:.3f}'} "
              f"{r.error}", file=sys.stderr)

    summary = summarize(results)
    args.out.write_text(json.dumps(
        {"summary": summary, "results": [asdict(r) for r in results]}, indent=2
    ))
    print(json.dumps(summary, indent=2))
    for warning in summary.get("environment_warnings", []):
        print(f"::warning::{warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
