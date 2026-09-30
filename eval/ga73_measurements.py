"""Predeclared downstream pilot after B1: 25 real bugs + 40 settled Python merges.

No host corpus installers. Safety/policy refusals stay in denominators. Clean
merge screening is NOT ground truth; independent adjudication remains required.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.false_positives import changed_python_files, select_pairs, summarize_rows  # noqa: E402
from eval.ga73_collection import collection_screen  # noqa: E402
from eval.run_bugsinpy import discover, ensure_repo, evaluate_one, summarize  # noqa: E402
from jittest.config import load_config  # noqa: E402
from jittest.llm import build_llm  # noqa: E402
from jittest.pipeline import run  # noqa: E402

MODEL = "melious/glm-5.3-flash"
DATASET_SHA = "11c5f1eea954a42132cfd06bf257766a7963e0fd"
PROJECTS = ["PySnooper", "tqdm", "youtube-dl"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bugsinpy", type=Path, required=True)
    ap.add_argument("--smoke", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("ga73-measurements.json"))
    ap.add_argument("--bugs-only", action="store_true")
    ap.add_argument("--bug-risk-threshold", type=float, choices=(0.0, 0.35), default=0.0)
    args = ap.parse_args()
    evidence = {"scope": "predeclared real-corpus pilot; clean-merge screening proxy, not definitive FPR",
                "ga_ready": False, "model": MODEL, "independent_adjudication": "pending",
                "dataset_sha": DATASET_SHA, "projects": PROJECTS, "bug_limit": 25, "fp_limit": 40,
                "fp_since": "5 years ago", "fp_until": "90 days ago",
                "bug_risk_threshold": args.bug_risk_threshold, "fp_risk_threshold": 0.35,
                "max_targets": 5, "candidates_per_target": 4,
                "accounted_budget_usd": {"bugs": 2.0, "fp": 1.0},
                "budget_caveat": "Response-accounted list-price guard, not provider-side reservation. A request can overshoot; timeouts can have unobserved spend.",
                "fx_usd_per_eur": os.getenv("JITTEST_EUR_USD"), "bug_results": [], "fp_results": []}
    qualified = False
    try:
        smoke = json.loads(args.smoke.read_text())
        if not smoke.get("acceptance", {}).get("passed"):
            raise ValueError("B1 must pass before scaling")
        actual = subprocess.check_output(["git", "-C", str(args.bugsinpy), "rev-parse", "HEAD"], text=True).strip()
        if actual != DATASET_SHA or os.getenv("JITTEST_SANDBOX") != "required":
            raise ValueError("frozen corpus and required isolation are mandatory")
        evidence["code_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        evidence["runtime_image"] = os.environ["JITTEST_RUNTIME_IMAGE"]
        evidence["host_provisioning"] = False
        specs = discover(args.bugsinpy, 25, PROJECTS)
        evidence["manifest"] = [asdict(s) for s in specs]
        work = Path("/tmp/jittest-ga73-measurements")
        work.mkdir(parents=True, exist_ok=True)
        bug_rows, spent = [], 0.0
        fp_repo = None
        for spec in specs:
            if spent >= 2.0:
                evidence["bug_abort"] = "accounted_budget_exhausted"
                break
            repo, reason = ensure_repo(spec, work)
            if repo is None or reason.startswith("commits-missing"):
                raise ValueError("frozen corpus revision unavailable")
            if spec.project == "youtube-dl":
                fp_repo = repo
            result = evaluate_one(spec, repo, MODEL, 2.0 - spent, risk_threshold=args.bug_risk_threshold)
            result.runner = "pytest"
            # Unlike B1, do not assert every project's dependencies are proved.
            result.deps_status = "predeclared-runtime; inspect collection outcomes"
            spent += result.cost_usd
            bug_rows.append(result)
            evidence["bug_results"] = [asdict(r) for r in bug_rows]
            evidence["bug_summary"] = summarize(bug_rows)
            evidence["bug_accounted_usd"] = spent
            args.out.write_text(json.dumps(evidence, indent=2) + "\n")
            if result.diff_status in ("model_unavailable", "quota_exhausted"):
                evidence["bug_abort"] = result.diff_status
                break
        if args.bugs_only:
            telemetry = [t for row in evidence["bug_results"] for t in row["telemetry"]]
            screen = collection_screen(telemetry)
            healthy = screen["healthy_collection"]
            evidence["bug_collection_screen"] = screen
            paired = any(t.get("head_outcome") in ("pass", "fail") and
                         t.get("base_outcome") in ("pass", "fail") for t in telemetry)
            qualified = (len(bug_rows) == 25 and evidence["bug_summary"]["completion_rate"] >= 0.8
                         and healthy and paired)
            evidence.update(scope="Default-operating-point real-bug cohort; not a standalone precision/GA claim",
                            collection_qualified=qualified, healthy_collection=healthy,
                            bug_execution_pair_present=paired)
            args.out.write_text(json.dumps(evidence, indent=2) + "\n")
            print("Default bug cohort captured; pair with matching-threshold PR evidence.")
            return 0 if qualified else 1
        if fp_repo is None:
            raise ValueError("no approved repository for settled-merge pilot")
        evidence["fp_repo"] = next(s.repo_url for s in specs if s.project == "youtube-dl")
        evidence["fp_repo_sha"] = subprocess.check_output(["git", "-C", str(fp_repo), "rev-parse", "HEAD"], text=True).strip()
        pairs, screened = select_pairs(fp_repo, 40, since="5 years ago", until="90 days ago")
        evidence["fp_manifest"] = [{"base": b, "head": h} for b, h in pairs]
        rows, spent = [], 0.0
        for base, head in pairs:
            if spent >= 1.0:
                evidence["fp_abort"] = "accounted_budget_exhausted"
                break
            cfg = load_config(fp_repo, overrides={"model": MODEL, "budget_usd": 1.0 - spent,
                "max_targets": 5, "candidates_per_target": 4, "risk_threshold": 0.35})
            llm = build_llm(MODEL, budget_usd=cfg.budget_usd, temperature=cfg.temperature,
                            request_ceiling=25, http_timeout=30)
            report = run(fp_repo, base, head, cfg, llm)
            spent += report.cost_usd
            reported = [f for f in report.findings if f.assessment.should_report]
            rows.append({"base": base, "head": head, "reported": len(reported),
                "cost_usd": report.cost_usd, "priced": report.priced,
                "provider_billing": report.provider_billing,
                "input_tokens": report.input_tokens, "output_tokens": report.output_tokens,
                "tokens_estimated": report.tokens_estimated, "model_requests": report.model_requests,
                "model_request_attempts": report.model_request_attempts,
                "diff_status": report.diff_status, "targets_considered": report.targets_considered,
                "candidates_generated": report.candidates_generated,
                "python_files_changed": len(changed_python_files(fp_repo, base, head)),
                "claims": [f.assessment.summary for f in reported],
                "claim_cases": [{"file": f.target.file_path, "symbol": f.target.symbol,
                    "test_code": f.test_code, "source_before": f.target.source_before,
                    "source_after": f.target.source_after, "assessment": f.assessment.as_dict(),
                    "failure_excerpt": getattr(f, "failure_excerpt", "")} for f in reported],
                "telemetry": [t.as_dict() for t in report.telemetry], "sandbox": report.sandbox})
            evidence["fp_results"] = rows
            evidence["fp_accounted_usd"] = spent
            evidence["fp_summary"] = summarize_rows(rows, len(pairs), screened_out=screened,
                                                     window=("5 years ago", "90 days ago"))
            args.out.write_text(json.dumps(evidence, indent=2) + "\n")
            if report.diff_status in ("model_unavailable", "quota_exhausted"):
                evidence["fp_abort"] = report.diff_status
                break
        bs, fs = evidence["bug_summary"], evidence["fp_summary"]
        bug_tel = [t for r in evidence["bug_results"] for t in r["telemetry"]]
        fp_tel = [t for r in rows for t in r["telemetry"]]
        bug_screen, fp_screen = collection_screen(bug_tel), collection_screen(fp_tel)
        healthy = bug_screen["healthy_collection"] and fp_screen["healthy_collection"]
        evidence.update(bug_collection_screen=bug_screen, fp_collection_screen=fp_screen)
        paired = any(t.get("head_outcome") in ("pass", "fail") and
                     t.get("base_outcome") in ("pass", "fail") for t in bug_tel)
        evidence["healthy_collection"] = healthy
        evidence["bug_execution_pair_present"] = paired
        qualified = (len(bug_rows) == 25 and bs["completion_rate"] >= 0.8
                     and fs["gate_ready"] and fs["sample_floor_met"] and healthy and paired)
        evidence["collection_qualified"] = qualified
    except Exception as exc:
        evidence["error_type"] = type(exc).__name__
        evidence["collection_qualified"] = False
    args.out.write_text(json.dumps(evidence, indent=2) + "\n")
    print("Pilot artifacts captured; publication still requires independent ground truth." if qualified
          else "Pilot qualification failed; raw outcomes retained, no GA metrics publication.")
    return 0 if qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())
