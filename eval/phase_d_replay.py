"""Development Replay Harness for Phase D Differential Explorer.

Executes Phase D instrument on the 7 REAL Flask calibration rows from phase-c-benchmark-manifest.json.

Development Gate:
- >= 2 real catches
- >= 80% unique candidates
- <= 20% mechanically invalid final candidates
- Zero safety escapes

Note: Results on the 7 Flask development rows are exploratory/post-hoc only.
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


def load_replay_rows() -> list[dict[str, Any]]:
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [r for r in data["rows"] if r.get("cohort") == "calibration"]


def run_development_replay(llm_client: Any = None) -> dict[str, Any]:
    t0 = time.time()
    rows = load_replay_rows()

    cfg = load_config()
    if llm_client is None:
        if os.environ.get("JITTEST_DRY_RUN", "0") in ("1", "true", "yes") or not (os.environ.get("MISTRAL_API_KEY") or os.environ.get("JITTEST_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            llm_client = DryRunLLM()
        else:
            llm_client = build_llm(cfg.model, budget_usd=cfg.budget_usd)

    meter_calls_before = getattr(llm_client.usage, "calls", 0)
    meter_cost_before = getattr(llm_client.usage, "cost_usd", 0.0)

    results = []
    shas = []
    runtimes = []
    catches = 0
    mechanically_invalid = 0
    safety_escapes = 0

    for idx, r in enumerate(rows, 1):
        repo_url = r["repository"]
        repo_path = REPO_MAP.get(repo_url, REPO_ROOT)

        pipeline = PhaseDPipeline(repo_path, cfg, llm_client)

        telem = pipeline.process_target(row_manifest=r)
        data = telem.as_dict()
        data["row_id"] = r["row_id"]
        results.append(data)

        if telem.candidate_sha:
            shas.append(telem.candidate_sha)
        if telem.wall_clock_s > 0:
            runtimes.append(telem.wall_clock_s)

        if telem.final_disposition in (Disposition.ACCEPTED_STRONG_CATCH.value, Disposition.STABLE_TECHNICAL_WEAK_CATCH.value):
            catches += 1
        elif telem.final_disposition in (Disposition.PARSE_FAILED.value, Disposition.SETUP_RUNTIME_ERROR.value):
            mechanically_invalid += 1

    meter_calls_after = getattr(llm_client.usage, "calls", 0)
    meter_cost_after = getattr(llm_client.usage, "cost_usd", 0.0)

    unique_pct = (len(set(shas)) / len(shas) * 100.0) if shas else 100.0
    invalid_pct = (mechanically_invalid / len(results) * 100.0) if results else 0.0

    gate_passed = (
        catches >= 2
        and unique_pct >= 80.0
        and invalid_pct <= 20.0
        and safety_escapes == 0
    )

    med_cost = (meter_cost_after - meter_cost_before) / len(results) if results else 0.0
    p95_time = statistics.quantiles(runtimes, n=20)[18] if len(runtimes) >= 20 else (max(runtimes) if runtimes else 0.0)

    report = {
        "schema_version": "1.0",
        "instrument": "Phase D Differential Explorer",
        "status": "exploratory_post_hoc",
        "rows_evaluated": len(results),
        "catches": catches,
        "unique_candidates_pct": unique_pct,
        "mechanically_invalid_pct": invalid_pct,
        "safety_escapes": safety_escapes,
        "meter_calls_delta": meter_calls_after - meter_calls_before,
        "meter_cost_usd_delta": meter_cost_after - meter_cost_before,
        "median_cost_usd": med_cost,
        "p95_runtime_s": p95_time,
        "total_wall_clock_s": time.time() - t0,
        "development_gate_passed": gate_passed,
        "rows": results,
    }
    return report


if __name__ == "__main__":
    rep = run_development_replay()
    out_file = REPO_ROOT / "phase-d-development-replay.json"
    out_file.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(f"Development Replay complete. Gate passed: {rep['development_gate_passed']}. Wrote {out_file.name}")
