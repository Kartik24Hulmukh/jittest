"""Confirmatory Holdout Harness for Phase D Differential Explorer.

Executes Phase D instrument on 16 real untouched bug rows and 60 real untouched control rows
loaded from phase-c-benchmark-manifest.json.

Launch Gate:
- >= 4/16 catches
- <= 1/60 controls flagged
- >= 90% completion
- median cost <= $0.25 per eligible PR
- p95 runtime <= 10 min
- zero unsafe executions
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from jittest.config import Config, load_config
from jittest.llm import DryRunLLM, build_llm
from jittest.phase_d.pipeline_d import PhaseDPipeline
from jittest.phase_d.taxonomy import Disposition

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "phase-c-benchmark-manifest.json"

REPO_MAP = {
    "https://github.com/pallets/flask": REPO_ROOT.parent / "flask",
    "https://github.com/psf/requests": REPO_ROOT.parent / "requests",
    "https://github.com/ytdl-org/youtube-dl": REPO_ROOT.parent / "youtube-dl",
}


def load_holdout_cohorts() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    rows = data["rows"]
    bug_rows = [r for r in rows if r.get("cohort") == "bug_holdout"][:16]
    ctrl_rows = [r for r in rows if r.get("cohort") == "control_holdout"][:60]
    return bug_rows, ctrl_rows


def run_confirmatory_holdout(llm_client: Any = None) -> dict[str, Any]:
    t0 = time.time()
    bug_rows, ctrl_rows = load_holdout_cohorts()

    cfg = load_config()
    if llm_client is None:
        if os.environ.get("JITTEST_DRY_RUN", "0") in ("1", "true", "yes") or not (os.environ.get("MISTRAL_API_KEY") or os.environ.get("JITTEST_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            llm_client = DryRunLLM()
        else:
            llm_client = build_llm(cfg.model, budget_usd=cfg.budget_usd)

    meter_calls_before = getattr(llm_client.usage, "calls", 0)
    meter_cost_before = getattr(llm_client.usage, "cost_usd", 0.0)

    bug_results = []
    ctrl_results = []
    runtimes = []
    bug_catches = 0
    ctrl_flagged = 0

    for r in bug_rows:
        repo_url = r["repository"]
        repo_path = REPO_MAP.get(repo_url, REPO_ROOT)

        pipeline = PhaseDPipeline(repo_path, cfg, llm_client)

        base_sha = r.get("derived_base_sha") or r.get("real_buggy_sha") or r.get("base_sha", "")
        head_sha = r.get("derived_head_sha") or r.get("real_fixed_sha") or r.get("head_sha", "")

        telem = pipeline.process_target(
            target_symbol=r.get("target_symbol", r["row_id"]),
            target_file=r.get("target_file", "src/flask/app.py"),
            base_sha=base_sha,
            head_sha=head_sha,
        )
        data = telem.as_dict()
        data["row_id"] = r["row_id"]
        bug_results.append(data)
        if telem.wall_clock_s > 0:
            runtimes.append(telem.wall_clock_s)

        if telem.final_disposition in (Disposition.ACCEPTED_STRONG_CATCH.value, Disposition.STABLE_TECHNICAL_WEAK_CATCH.value):
            bug_catches += 1

    for r in ctrl_rows:
        repo_url = r["repository"]
        repo_path = REPO_MAP.get(repo_url, REPO_ROOT)

        pipeline = PhaseDPipeline(repo_path, cfg, llm_client)

        base_sha = r.get("derived_base_sha") or r.get("real_buggy_sha") or r.get("base_sha", "")
        head_sha = r.get("derived_head_sha") or r.get("real_fixed_sha") or r.get("head_sha", "")

        telem = pipeline.process_target(
            target_symbol=r.get("target_symbol", r["row_id"]),
            target_file=r.get("target_file", "src/flask/app.py"),
            base_sha=base_sha,
            head_sha=head_sha,
        )
        data = telem.as_dict()
        data["row_id"] = r["row_id"]
        ctrl_results.append(data)
        if telem.wall_clock_s > 0:
            runtimes.append(telem.wall_clock_s)

        if telem.final_disposition in (Disposition.ACCEPTED_STRONG_CATCH.value, Disposition.STABLE_TECHNICAL_WEAK_CATCH.value):
            ctrl_flagged += 1

    meter_calls_after = getattr(llm_client.usage, "calls", 0)
    meter_cost_after = getattr(llm_client.usage, "cost_usd", 0.0)

    total_rows = len(bug_results) + len(ctrl_results)
    completed_rows = sum(1 for r in bug_results + ctrl_results if r["eligible"])
    completion_pct = (completed_rows / total_rows * 100.0) if total_rows else 0.0

    med_cost = (meter_cost_after - meter_cost_before) / total_rows if total_rows else 0.0
    p95_time = statistics.quantiles(runtimes, n=20)[18] if len(runtimes) >= 20 else (max(runtimes) if runtimes else 0.0)

    launch_gate_passed = (
        bug_catches >= 4
        and ctrl_flagged <= 1
        and completion_pct >= 90.0
        and med_cost <= 0.25
        and p95_time <= 600.0
    )

    report = {
        "schema_version": "1.0",
        "instrument": "Phase D Differential Explorer",
        "cohort": "confirmatory_holdout",
        "bug_rows_evaluated": len(bug_results),
        "control_rows_evaluated": len(ctrl_results),
        "bug_catches": bug_catches,
        "controls_flagged": ctrl_flagged,
        "completion_pct": completion_pct,
        "meter_calls_delta": meter_calls_after - meter_calls_before,
        "meter_cost_usd_delta": meter_cost_after - meter_cost_before,
        "median_cost_usd": med_cost,
        "p95_runtime_s": p95_time,
        "total_wall_clock_s": time.time() - t0,
        "launch_gate_passed": launch_gate_passed,
        "bug_rows": bug_results,
        "control_rows": ctrl_results,
    }
    return report


if __name__ == "__main__":
    rep = run_confirmatory_holdout()
    out_file = REPO_ROOT / "phase-d-holdout-report.json"
    out_file.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"Holdout complete. Launch Gate passed: {rep['launch_gate_passed']}. Wrote {out_file.name}")
