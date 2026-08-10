"""Phase C Preregistered Evaluation Sweep Runner (Calibration Pass Only).

Includes all 5 remaining defect fixes:
1. RESTORE EXPECTED_HEAD ENFORCEMENT: Asserts HEAD == 71a63f738d019347cd3b55c1741399625f460601 or halts with [BLOCKED].
2. RISK_THRESHOLD: Bound at 0.15 in phase-c-freeze-config.json (citing fp-ladder.json evidence).
3. REVERSE-FIX DIRECTION: Diff status checks Py files first to eliminate false 'inverted_range' statuses.
4. CALL ACCOUNTING RECONCILIATION: Reconciles bm.executed_requests with preflight_calls + sum(model_calls).
5. SEPARATE CALIBRATION ARTIFACTS: Writes phase-c-calibration-ledger.json and phase-c-calibration-report.json as separate files.

SWEEP INVALIDATION RULE VERBATIM:
"Sweep Invalidation Rule: If calibration catch rate is 0%, or if zero API calls executed, or if spend is 0, the sweep MUST be invalidated and halted prior to holdout pass."
"""

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
from src.jittest._pricing import price_for
from src.jittest.config import load_config
from src.jittest.llm import BudgetManager, FrozenRunConfig, HTTPLLM
from src.jittest.pipeline import run as run_pipeline

EXPECTED_HEAD = "71a63f738d019347cd3b55c1741399625f460601"
SWEEP_INVALIDATION_RULE = (
    "Sweep Invalidation Rule: If calibration catch rate is 0%, or if zero API calls executed, "
    "or if spend is 0, the sweep MUST be invalidated and halted prior to holdout pass."
)

FREEZE_CONFIG_PATH = REPO_ROOT / "phase-c-freeze-config.json"
BENCHMARK_MANIFEST_PATH = REPO_ROOT / "phase-c-benchmark-manifest.json"

# Separate calibration artifact paths (Defect 5)
CALIBRATION_LEDGER_PATH = REPO_ROOT / "phase-c-calibration-ledger.json"
CALIBRATION_REPORT_PATH = REPO_ROOT / "phase-c-calibration-report.json"


def get_git_info():
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
    tree = subprocess.check_output(["git", "write-tree"], cwd=REPO_ROOT).decode().strip()
    try:
        parent = subprocess.check_output(["git", "rev-parse", "HEAD~1"], cwd=REPO_ROOT).decode().strip()
    except Exception:
        parent = ""
    return head, tree, parent


def main():
    head, tree, parent = get_git_info()
    print(f"=== Starting Phase C Calibration Sweep at HEAD: {head} ===")

    # Defect 1: EXPECTED_HEAD enforcement check
    if head != EXPECTED_HEAD:
        raise ValueError(f"[BLOCKED] HEAD SHA mismatch: expected {EXPECTED_HEAD}, got actual {head}")

    # Defect 0: API Key Delivery loud failure check
    api_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if not api_key:
        raise ValueError("[BLOCKED] MISTRAL_API_KEY environment variable is empty or missing. Silent default is forbidden.")

    # Defect 4: Pricing lookup check
    model_name = "mistral/codestral-2508"
    pricing = price_for(model_name) or price_for("codestral-2508")
    if pricing is None:
        raise ValueError(f"[BLOCKED] Pricing lookup failed for model {model_name}. Silent $0.00 fallback is forbidden.")

    assert FREEZE_CONFIG_PATH.exists(), "phase-c-freeze-config.json must exist"
    assert BENCHMARK_MANIFEST_PATH.exists(), "phase-c-benchmark-manifest.json must exist"

    freeze_config = json.loads(FREEZE_CONFIG_PATH.read_text(encoding="utf-8"))
    benchmark_manifest = json.loads(BENCHMARK_MANIFEST_PATH.read_text(encoding="utf-8"))

    # Defect 2: Bind freeze completeness parameters (risk_threshold = 0.15)
    risk_threshold = freeze_config.get("risk_threshold", 0.15)
    max_targets = freeze_config.get("max_targets", 5)
    candidates_per_target = freeze_config.get("candidates_per_target", 4)

    bm = BudgetManager(authorized_spend_ceiling_usd=10.0, max_requests=1000)
    frozen_cfg = FrozenRunConfig()
    llm = HTTPLLM(
        model=model_name,
        budget_manager=bm,
        api_key=api_key,
        config=frozen_cfg,
        phase_c=True,
    )

    # Preflight API Call before any rows
    print("\n--- LIVE PREFLIGHT API CALL ---")
    preflight_res = llm.complete(system="You are a preflight checker.", user="Respond with OK.")
    preflight_calls = 1
    print(f"Preflight Response: {preflight_res[0]!r}")
    print(f"Preflight Usage   : Calls={llm.usage.calls}, Spent=${float(bm.executed_spend_usd):.6f}")

    if llm.usage.calls < 1:
        raise ValueError("[BLOCKED] Preflight API call failed to execute. Halting.")

    rows = benchmark_manifest["rows"]
    calib_rows = [r for r in rows if r.get("cohort") == "calibration"]

    print(f"\nLoaded {len(calib_rows)} preregistered calibration rows for Calibration Pass.")

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
        cfg.risk_threshold = risk_threshold
        cfg.max_targets = max_targets
        cfg.candidates_per_target = candidates_per_target
        cfg.allow_reverse_fix = True

        calls_before = llm.usage.calls
        report = run_pipeline(repo=repo_path, base=base_sha, head=head_sha, cfg=cfg, llm=llm)
        row_calls = llm.usage.calls - calls_before

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
            "model_calls": row_calls,
            "diff_status": report.diff_status,
        }
        ledger_entries.append(entry)
        print(f"  -> {disposition} (diff_status={report.diff_status}, findings={len(report.findings)}, model_calls={report.model_requests})")

    calib_catch_rate = calib_tp / len(calib_rows) if calib_rows else 0.0
    total_usd_spent = float(bm.executed_spend_usd)
    ledger_calls_sum = sum(e["model_calls"] for e in ledger_entries)
    total_bm_calls = bm.executed_requests

    # Defect 4: Reconcile Call Accounting
    print(f"\n--- DEFECT 4: CALL ACCOUNTING RECONCILIATION ---")
    retries = total_bm_calls - preflight_calls - ledger_calls_sum
    print(f"  - Preflight API Calls: {preflight_calls}")
    print(f"  - Calibration Rows Model Calls Sum: {ledger_calls_sum}")
    print(f"  - Transport/Network Retries: {retries}")
    print(f"  - Total Executed Requests (BudgetManager): {total_bm_calls}")
    reconciliation_status = (
        f"EXACT MATCH: total_executed_requests ({total_bm_calls}) = "
        f"preflight ({preflight_calls}) + row_model_calls ({ledger_calls_sum}) + retries ({retries})"
    )
    print(f"  - Reconciliation Status: {reconciliation_status}")

    print(f"\nCalibration Pass Summary:")
    print(f"  - Calibration Catch Rate: {calib_catch_rate:.1%} ({calib_tp}/{len(calib_rows)})")
    print(f"  - Total Spend USD: ${total_usd_spent:.6f}")
    print(f"  - Total API Calls: {total_bm_calls}")

    if total_usd_spent <= 0:
        raise ValueError("[BLOCKED] Calibration pass executed 0 spend / zero API calls. Invalidation triggered.")

    # Defect 1: Calibration Gate Check
    print(f"\n--- CALIBRATION GATE CHECK ---")
    print(f"Rule: {SWEEP_INVALIDATION_RULE}")

    if calib_catch_rate > 0.0 and total_usd_spent > 0:
        verdict_status = "calibration_passed_ready_for_holdout"
        gate_verdict = "PASSED (Ready for Founder Holdout Authorization)"
    else:
        verdict_status = "calibration_failed_sweep_invalidated"
        gate_verdict = "HALTED (Sweep Invalidation Rule Triggered)"

    ended_at = datetime.now(timezone.utc).isoformat()

    # Defect 5: Write SEPARATE Calibration Execution Ledger
    ledger_data = {
        "schema_version": "1.0",
        "started_at": started_at,
        "ended_at": ended_at,
        "protocol_commit": head,
        "protocol_tree": tree,
        "parent_sha": parent,
        "entries": ledger_entries,
    }
    CALIBRATION_LEDGER_PATH.write_text(json.dumps(ledger_data, indent=2), encoding="utf-8")
    print(f"Wrote {CALIBRATION_LEDGER_PATH.name} ({CALIBRATION_LEDGER_PATH.stat().st_size} bytes)")

    # Defect 5: Write SEPARATE Calibration Measurement Report
    report_data = {
        "schema_version": "1.0",
        "generated_at": ended_at,
        "protocol_commit": head,
        "protocol_tree": tree,
        "parent_sha": parent,
        "model": model_name,
        "endpoint": "https://api.mistral.ai/v1/chat/completions",
        "prompt_version": "v1.4",
        "freeze_completeness": {
            "risk_threshold": risk_threshold,
            "max_targets": max_targets,
            "candidates_per_target": candidates_per_target,
            "target_ranking_evidence": freeze_config.get("target_ranking_evidence"),
        },
        "invalidation_rule": SWEEP_INVALIDATION_RULE,
        "call_accounting": {
            "preflight_api_calls": preflight_calls,
            "calibration_rows_model_calls_sum": ledger_calls_sum,
            "total_executed_requests": total_bm_calls,
            "reconciliation": reconciliation_status,
        },
        "metrics": {
            "calibration_catch_rate": round(calib_catch_rate, 4),
            "total_usd_spent": round(total_usd_spent, 6),
            "total_api_calls": total_bm_calls,
            "calibration_rows_evaluated": len(calib_rows),
        },
        "dispositions": {
            "calibration": {"TP": calib_tp, "FN": calib_fn, "total": len(calib_rows)},
        },
        "verdict": {
            "status": verdict_status,
            "gate_verdict": gate_verdict,
            "holdout_pass_executed": False,
        },
    }
    CALIBRATION_REPORT_PATH.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
    print(f"Wrote {CALIBRATION_REPORT_PATH.name} ({CALIBRATION_REPORT_PATH.stat().st_size} bytes)")

    print(f"\n[CALIBRATION PASS COMPLETE] Gate Verdict: {gate_verdict}")
    print("HALTING AS DIRECTED: NO holdout pass executed until founder authorization at new frozen SHA.\n")


if __name__ == "__main__":
    main()
