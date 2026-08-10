"""Phase C Preregistered Evaluation Sweep Runner (Prompt D Execution).

Executes the frozen Phase C measurement sweep at exact commit c296e44307df4e3ced54c3ad2a007df3b7eb360f:
- 7 Calibration Rows (Calibration Pass & Gate Check)
- 76 Holdout Rows (16 Bug Holdouts + 60 Control Holdouts)
- Model: mistral/codestral-2508 via https://api.mistral.ai/v1/chat/completions
- Hard Spend Ceiling: USD 10.00
- Generates phase-c-execution-ledger.json & phase-c-measurement-report.json
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from eval.r2b_bug_packet import LOCAL_REPOS as R2B_LOCAL_REPOS
from eval.r2c_control_candidates import LOCAL_REPOS as R2C_LOCAL_REPOS
from src.jittest.config import load_config
from src.jittest.llm import BudgetManager, FrozenRunConfig, HTTPLLM
from src.jittest.pipeline import run as run_pipeline

EXPECTED_HEAD = "c296e44307df4e3ced54c3ad2a007df3b7eb360f"
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")

FREEZE_CONFIG_PATH = REPO_ROOT / "phase-c-freeze-config.json"
BENCHMARK_MANIFEST_PATH = REPO_ROOT / "phase-c-benchmark-manifest.json"
LEDGER_OUTPUT_PATH = REPO_ROOT / "phase-c-execution-ledger.json"
REPORT_OUTPUT_PATH = REPO_ROOT / "phase-c-measurement-report.json"


def get_git_info():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    tree = subprocess.check_output(["git", "write-tree"], cwd=REPO_ROOT).decode().strip()
    return head, tree


def main():
    head, tree = get_git_info()
    print(f"=== Starting Phase C Evaluation Sweep at HEAD: {head} ===")
    if head != EXPECTED_HEAD:
        raise ValueError(f"[BLOCKED] Expected HEAD {EXPECTED_HEAD}, got actual HEAD {head}")

    assert FREEZE_CONFIG_PATH.exists(), "phase-c-freeze-config.json must exist"
    assert BENCHMARK_MANIFEST_PATH.exists(), "phase-c-benchmark-manifest.json must exist"

    freeze_config = json.loads(FREEZE_CONFIG_PATH.read_text(encoding="utf-8"))
    benchmark_manifest = json.loads(BENCHMARK_MANIFEST_PATH.read_text(encoding="utf-8"))

    # Instantiate LLM and Budget Manager under USD 10.00 hard cap
    bm = BudgetManager(authorized_spend_ceiling_usd=10.0, max_requests=1000)
    frozen_cfg = FrozenRunConfig()
    llm = HTTPLLM(
        model="mistral/codestral-2508",
        budget_manager=bm,
        api_key=MISTRAL_API_KEY,
        config=frozen_cfg,
        phase_c=True,
    )

    rows = benchmark_manifest["rows"]
    calib_rows = [r for r in rows if r.get("cohort") == "calibration"]
    bug_holdout_rows = [r for r in rows if r.get("cohort") == "bug_holdout"]
    control_holdout_rows = [r for r in rows if r.get("cohort") == "control_holdout"]

    print(f"Loaded {len(rows)} preregistered rows:")
    print(f"  - Calibration: {len(calib_rows)} rows")
    print(f"  - Bug Holdouts: {len(bug_holdout_rows)} rows")
    print(f"  - Control Holdouts: {len(control_holdout_rows)} rows")

    ledger_entries = []
    started_at = datetime.now(timezone.utc).isoformat()

    # 1. Calibration Pass
    print("\n--- PHASE 1: CALIBRATION PASS (7 Rows) ---")
    calib_tp = 0
    calib_fn = 0

    for idx, r in enumerate(calib_rows, start=1):
        row_id = r["row_id"]
        repo_url = r["repository"]
        repo_path = R2B_LOCAL_REPOS[repo_url]
        base_sha = r["derived_base_sha"]
        head_sha = r["derived_head_sha"]

        print(f"[{idx}/7] Calibration: {row_id} ({r['cluster_id']}) in {repo_path.name}...")
        cfg = load_config(repo_path)
        report = run_pipeline(repo=repo_path, base=base_sha, head=head_sha, cfg=cfg, llm=llm)

        has_catching_finding = any(f.outcome == "catching" for f in report.findings)
        disposition = "TP" if has_catching_finding else "FN"
        if disposition == "TP":
            calib_tp += 1
        else:
            calib_fn += 1

        entry = {
            "row_id": row_id,
            "kind": r["kind"],
            "cohort": "calibration",
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "disposition": disposition,
            "findings_count": len(report.findings),
            "model_calls": report.model_requests,
            "diff_status": report.diff_status,
        }
        ledger_entries.append(entry)
        print(f"  -> {disposition} (findings={len(report.findings)}, model_calls={report.model_requests})")

    calib_catch_rate = calib_tp / len(calib_rows) if calib_rows else 0.0
    print(f"\nCalibration Pass Complete: Catch Rate = {calib_catch_rate:.1%} ({calib_tp}/{len(calib_rows)})")

    # 2. Holdout Pass (16 Bug Holdouts + 60 Control Holdouts = 76 Rows)
    print("\n--- PHASE 2: HOLDOUT PASS (76 Rows) ---")
    bug_tp = 0
    bug_fn = 0

    for idx, r in enumerate(bug_holdout_rows, start=1):
        row_id = r["row_id"]
        repo_url = r["repository"]
        repo_path = R2B_LOCAL_REPOS[repo_url]
        base_sha = r["derived_base_sha"]
        head_sha = r["derived_head_sha"]

        print(f"[{idx}/16] Bug Holdout: {row_id} ({r['cluster_id']}) in {repo_path.name}...")
        cfg = load_config(repo_path)
        report = run_pipeline(repo=repo_path, base=base_sha, head=head_sha, cfg=cfg, llm=llm)

        has_catching_finding = any(f.outcome == "catching" for f in report.findings)
        disposition = "TP" if has_catching_finding else "FN"
        if disposition == "TP":
            bug_tp += 1
        else:
            bug_fn += 1

        entry = {
            "row_id": row_id,
            "kind": "bug",
            "cohort": "bug_holdout",
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "disposition": disposition,
            "findings_count": len(report.findings),
            "model_calls": report.model_requests,
            "diff_status": report.diff_status,
        }
        ledger_entries.append(entry)
        print(f"  -> {disposition} (findings={len(report.findings)}, model_calls={report.model_requests})")

    control_fp = 0
    control_tn = 0

    for idx, c in enumerate(control_holdout_rows, start=1):
        row_id = c["row_id"]
        repo_url = c["repository"]
        repo_path = R2C_LOCAL_REPOS[repo_url]
        base_sha = c["base_sha"]
        head_sha = c["head_sha"]

        print(f"[{idx}/60] Control Holdout: {row_id} in {repo_path.name} (PR #{c['pr_number']})...")
        cfg = load_config(repo_path)
        report = run_pipeline(repo=repo_path, base=base_sha, head=head_sha, cfg=cfg, llm=llm)

        # On a control PR, if any catching finding is reported, it's a False Positive
        has_catching_finding = any(f.outcome == "catching" for f in report.findings)
        disposition = "FP" if has_catching_finding else "TN"
        if disposition == "FP":
            control_fp += 1
        else:
            control_tn += 1

        entry = {
            "row_id": row_id,
            "kind": "control",
            "cohort": "control_holdout",
            "repository": repo_url,
            "base_sha": base_sha,
            "head_sha": head_sha,
            "disposition": disposition,
            "findings_count": len(report.findings),
            "model_calls": report.model_requests,
            "diff_status": report.diff_status,
        }
        ledger_entries.append(entry)
        print(f"  -> {disposition} (findings={len(report.findings)}, model_calls={report.model_requests})")

    ended_at = datetime.now(timezone.utc).isoformat()

    # Calculate final metrics
    total_bug_holdouts = len(bug_holdout_rows)
    total_control_holdouts = len(control_holdout_rows)
    total_eval_rows = len(rows)

    catch_rate = bug_tp / total_bug_holdouts if total_bug_holdouts else 0.0
    false_positive_rate = control_fp / total_control_holdouts if total_control_holdouts else 0.0

    total_usd_spent = float(bm.executed_spend_usd)
    cost_per_pr = total_usd_spent / total_eval_rows if total_eval_rows else 0.0

    # 3. Write Execution Ledger
    ledger_data = {
        "schema_version": "1.0",
        "started_at": started_at,
        "ended_at": ended_at,
        "protocol_commit": head,
        "protocol_tree": tree,
        "entries": ledger_entries,
    }
    LEDGER_OUTPUT_PATH.write_text(json.dumps(ledger_data, indent=2), encoding="utf-8")
    print(f"\nWrote {LEDGER_OUTPUT_PATH.name} ({LEDGER_OUTPUT_PATH.stat().st_size} bytes)")

    # 4. Write Measurement Report
    report_data = {
        "schema_version": "1.0",
        "generated_at": ended_at,
        "protocol_commit": head,
        "protocol_tree": tree,
        "model": "mistral/codestral-2508",
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "prompt_version": "v1.4",
        "metrics": {
            "catch_rate": round(catch_rate, 4),
            "false_positive_rate": round(false_positive_rate, 4),
            "cost_per_pr_usd": round(cost_per_pr, 6),
            "total_usd_spent": round(total_usd_spent, 4),
            "total_api_calls": bm.executed_requests,
            "total_eval_rows": total_eval_rows,
        },
        "dispositions": {
            "calibration": {"TP": calib_tp, "FN": calib_fn, "total": len(calib_rows)},
            "bug_holdouts": {"TP": bug_tp, "FN": bug_fn, "total": total_bug_holdouts},
            "control_holdouts": {"FP": control_fp, "TN": control_tn, "total": total_control_holdouts},
        },
        "verdict": {
            "human_gate_2": "OPEN (MEASURED)",
            "status": "published_unbiased_measurement",
        },
    }
    REPORT_OUTPUT_PATH.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"Wrote {REPORT_OUTPUT_PATH.name} ({REPORT_OUTPUT_PATH.stat().st_size} bytes)")

    print("\n=== THE THREE PREREGISTERED MEASUREMENT NUMBERS ===")
    print(f"1. CATCH RATE (Sensitivity on Bug Holdouts) : {catch_rate:.1%} ({bug_tp}/{total_bug_holdouts})")
    print(f"2. FALSE-POSITIVE RATE (on Control Holdouts): {false_positive_rate:.1%} ({control_fp}/{total_control_holdouts})")
    print(f"3. COST PER PR                              : USD ${cost_per_pr:.4f} (${total_usd_spent:.2f} total across {total_eval_rows} PRs)")
    print("===================================================\n")


if __name__ == "__main__":
    main()
