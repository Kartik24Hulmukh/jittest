"""Command line interface. argparse, because a CI tool has no business dragging
Typer, Click and Rich into somebody else's dependency graph.

    jittest run --base main --head HEAD
    jittest run --dry-run          # whole pipeline, no model, no key, no cost
    jittest doctor                 # can this environment run jittest?
    jittest stats                  # what the ledger has learned
    jittest outcome <hash> fixed_code
    jittest export corpus.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import load_config
from .execute import detect_runner
from .ledger import HUMAN_OUTCOMES, Ledger
from .llm import LLMError, build_llm
from .pipeline import run as run_pipeline
from .report import to_markdown, to_terminal


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--repo", default=".", help="path to the git repository")
    p.add_argument("--base", default=os.getenv("JITTEST_BASE", "origin/main"))
    p.add_argument("--head", default=os.getenv("JITTEST_HEAD", "HEAD"))
    p.add_argument("--model", default=None)
    p.add_argument("--candidates", type=int, default=None,
                   help="candidate tests generated per target")
    p.add_argument("--max-targets", type=int, default=None)
    p.add_argument("--risk-threshold", type=float, default=None)
    p.add_argument("--budget", type=float, default=None, help="hard USD cap")
    p.add_argument("--timeout", type=int, default=None, help="per test run, seconds")
    p.add_argument("--reruns", type=int, default=None,
                   help="flakiness reruns on head (default 2)")
    p.add_argument("--latent", action="store_true",
                   help="also report faults that fail on base too")
    p.add_argument("--dry-run", action="store_true",
                   help="run everything with a stub model: no API key, no cost")
    p.add_argument("--comment", action="store_true", help="upsert a PR comment")
    p.add_argument("--fail-on-regression", action="store_true",
                   help="exit 1 when a confident regression is found")
    p.add_argument("--json", dest="as_json", action="store_true")
    p.add_argument("--markdown", metavar="PATH", default=None,
                   help="also write the markdown report to this file")
    p.add_argument("--telemetry-json", metavar="PATH", default=None,
                   help="write one JSON object per candidate to this file")
    p.add_argument("--quiet", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jittest",
        description="Generate tests that FAIL on your pull request and PASS on main.",
    )
    parser.add_argument("--version", action="version", version=f"jittest {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    _add_run_args(sub.add_parser("run", help="analyse a diff"))

    st = sub.add_parser("stats", help="summarise the local ledger")
    st.add_argument("--repo", default=".")
    st.add_argument("--json", dest="as_json", action="store_true")

    ex = sub.add_parser("export", help="export the corpus as JSONL")
    ex.add_argument("out")
    ex.add_argument("--repo", default=".")
    ex.add_argument("--with-source", action="store_true",
                    help="include repo names and test code (off by default)")

    oc = sub.add_parser("outcome", help="label what a human did with a finding")
    oc.add_argument("test_hash")
    oc.add_argument("outcome", choices=list(HUMAN_OUTCOMES))
    oc.add_argument("--note", default="")
    oc.add_argument("--repo", default=".")

    dr = sub.add_parser("doctor", help="check that this environment can run jittest")
    dr.add_argument("--repo", default=".")

    sub.add_parser("version", help="print the version")
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    cfg = load_config(repo, overrides={
        "model": args.model,
        "candidates_per_target": args.candidates,
        "max_targets": args.max_targets,
        "risk_threshold": args.risk_threshold,
        "budget_usd": args.budget,
        "timeout_s": args.timeout,
        "reruns": args.reruns,
        "latent_mode": True if args.latent else None,
        "fail_on_regression": True if args.fail_on_regression else None,
    })

    from .github import pr_context, upsert_pr_comment
    pr_title, pr_body = pr_context()

    try:
        llm = build_llm(cfg.model, dry_run=args.dry_run, budget_usd=cfg.budget_usd,
                        temperature=cfg.temperature, cache_path=repo / cfg.cache_path)
    except LLMError as exc:
        print(f"jittest: {exc}", file=sys.stderr)
        return 2

    emit = (lambda m: None) if args.quiet else (lambda m: print(f"  {m}", file=sys.stderr))
    report = run_pipeline(repo, args.base, args.head, cfg, llm,
                          pr_title=pr_title, pr_body=pr_body,
                          pr_ref=os.getenv("JITTEST_PR_NUMBER", ""),
                          on_event=emit)

    markdown = to_markdown(report)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(to_terminal(report))

    if args.markdown:
        try:
            Path(args.markdown).write_text(markdown or "", encoding="utf-8")
        except OSError as exc:
            print(f"  warning: could not write markdown to {args.markdown}: "
                  f"{exc}", file=sys.stderr)

    if args.telemetry_json:
        # Side-channel output must never lose a finding that was already proven.
        try:
            tel_path = Path(args.telemetry_json)
            tel_path.parent.mkdir(parents=True, exist_ok=True)
            with tel_path.open("w", encoding="utf-8") as tfh:
                for tel in report.telemetry:
                    tfh.write(tel.as_jsonl() + "\n")
        except OSError as exc:
            print(f"  warning: could not write telemetry to "
                  f"{args.telemetry_json}: {exc}", file=sys.stderr)

    if args.comment:
        # Posting is the LAST step and the least important one: the analysis is
        # finished and has already been printed to stdout. A GitHub outage, a
        # revoked token, an absent `gh` binary, or a malformed API response must
        # never convert a completed run into a non-zero exit - that is exactly
        # how a real, proven regression gets thrown away as "CI is broken".
        # Same family as Defect 29 (unguarded GITHUB_OUTPUT). Premortem P3-13.
        try:
            comment_status = upsert_pr_comment(markdown)
        except Exception as exc:
            comment_status = f"failed to comment: {exc!r}"
        print(f"  github: {comment_status}", file=sys.stderr)

    if os.getenv("GITHUB_OUTPUT"):
        # A CI runner with an unwritable or stale GITHUB_OUTPUT path must not
        # turn a completed analysis into a crash with a non-zero exit code.
        try:
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
                fh.write(
                    f"regressions={'true' if report.has_regression else 'false'}\n")
                fh.write(f"findings={len(report.findings)}\n")
                fh.write(f"cost_usd={report.cost_usd:.4f}\n")
        except OSError as exc:
            print(f"  warning: could not write GITHUB_OUTPUT: {exc}",
                  file=sys.stderr)

    if (args.fail_on_regression or cfg.fail_on_regression) and report.has_regression:
        return 1
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.repo))
    with Ledger(Path(args.repo) / cfg.ledger_path) as ledger:
        stats = ledger.stats()
    if args.as_json:
        print(json.dumps(stats, indent=2))
        return 0
    print("jittest ledger")
    for key, value in stats.items():
        print(f"  {key:22} {value}")
    if not stats["labelled"]:
        print("\n  No human outcomes recorded yet, so the precision numbers above")
        print("  are unknown rather than good. Label findings with `jittest outcome`.")
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.repo))
    with Ledger(Path(args.repo) / cfg.ledger_path) as ledger:
        n = ledger.export_jsonl(args.out, anonymise=not args.with_source)
    print(f"wrote {n} record(s) to {args.out} "
          f"({'with source' if args.with_source else 'anonymised'})")
    return 0


def _cmd_outcome(args: argparse.Namespace) -> int:
    cfg = load_config(Path(args.repo))
    with Ledger(Path(args.repo) / cfg.ledger_path) as ledger:
        n = ledger.mark_outcome_by_hash(args.test_hash, args.outcome, args.note)
    print(f"labelled {n} record(s) as {args.outcome}")
    return 0 if n else 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    cfg = load_config(repo)
    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'ok  ' if passed else 'FAIL'}] {label}"
              f"{(' - ' + detail) if detail else ''}")

    print(f"jittest {__version__} doctor")
    check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])

    git = subprocess.run(["git", "--version"], capture_output=True, text=True, errors="replace")
    check("git available", git.returncode == 0, git.stdout.strip())

    inside = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--is-inside-work-tree"],
        capture_output=True, text=True, errors="replace")
    check("inside a git repository", inside.stdout.strip() == "true", str(repo))

    runner = detect_runner()
    using_pytest = "pytest" in " ".join(runner)
    print(f"  [ok  ] test runner: "
          f"{'pytest' if using_pytest else 'built-in mini-runner'}")
    if not using_pytest:
        print("         pytest is not importable here, so the oracle will use the")
        print("         stdlib fallback, which does not support fixtures.")

    has_key = any(os.getenv(k) for k in
                  ("JITTEST_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"))
    print(f"  [{'ok  ' if has_key else 'warn'}] model API key "
          f"{'found' if has_key else 'NOT found - only --dry-run will work'}")

    # Check whether the configured model has known pricing.
    from .llm import PRICES
    model_name = cfg.model.split("/")[-1] if "/" in cfg.model else cfg.model
    is_priced = any(key in model_name for key in PRICES)
    if is_priced:
        print(f"  [ok  ] model '{cfg.model}' is priced — dollar cap active")
    else:
        print(f"  [warn] model '{cfg.model}' is unpriced — "
              f"request-count ceiling will be enforced instead of a dollar cap")

    print(f"  [ok  ] model {cfg.model}, budget ${cfg.budget_usd:.2f}, "
          f"max targets {cfg.max_targets}")
    print(f"  [ok  ] ledger {repo / cfg.ledger_path}")
    print(f"  [ok  ] {len(cfg.ignore)} ignore pattern(s)")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "stats":
        return _cmd_stats(args)
    if args.command == "export":
        return _cmd_export(args)
    if args.command == "outcome":
        return _cmd_outcome(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    print(__version__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
