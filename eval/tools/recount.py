"""Derives and computes all evaluation statistics from signed receipts and manifests.

Usage:
    python eval/tools/recount.py [--manifest eval/layer1b_manifest.json] [--evidence-dir docs/evidence/layer1b]

Outputs JSON with all recomputed counts.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any


def compute_recount(
    manifest_path: Path | str = "eval/layer1b_manifest.json",
    evidence_dir: Path | str = "docs/evidence/layer1b",
) -> dict[str, Any]:
    manifest_path = Path(manifest_path)
    evidence_dir = Path(evidence_dir)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest_data = json.load(f)

    manifest_rows = manifest_data.get("rows", [])
    bug_manifest_rows = [r for r in manifest_rows if r.get("kind") == "bug"]
    ctrl_manifest_rows = [r for r in manifest_rows if r.get("kind") == "control"]

    receipt_pattern = str(evidence_dir / "*_evidence.json")
    receipt_files = sorted(glob.glob(receipt_pattern))

    receipts: list[dict[str, Any]] = []
    for rf in receipt_files:
        with open(rf, encoding="utf-8") as f:
            r = json.load(f)
            r["_filename"] = os.path.basename(rf)
            r["_is_bug"] = os.path.basename(rf).startswith("bug_")
            receipts.append(r)

    total_cost_usd = sum(r.get("provider_cost_usd", 0.0) for r in receipts)

    dispositions: dict[str, int] = {}
    verdicts: dict[str, int] = {}

    bug_receipts = [r for r in receipts if r["_is_bug"]]
    ctrl_receipts = [r for r in receipts if not r["_is_bug"]]

    # Counts
    bug_proven_catch = 0
    bug_reproduction_catch = 0
    bug_collection_catch = 0
    bug_non_discriminating = 0
    bug_refuted = 0
    bug_inconclusive = 0
    bug_executed = 0

    ctrl_proven_catch = 0
    ctrl_reproduction_catch = 0
    ctrl_collection_catch = 0
    ctrl_non_discriminating = 0
    ctrl_refuted = 0
    ctrl_inconclusive = 0
    ctrl_executed = 0

    for r in receipts:
        disp = r.get("disposition", "unknown")
        verdict = r.get("verdict", "unknown")
        dispositions[disp] = dispositions.get(disp, 0) + 1
        verdicts[verdict] = verdicts.get(verdict, 0) + 1

        is_bug = r["_is_bug"]
        # A row is executed to definitive verdict if it is not inconclusive/refused
        is_definitive = verdict != "inconclusive"

        if is_bug:
            if is_definitive:
                bug_executed += 1
            if verdict == "proven_catch":
                bug_proven_catch += 1
            elif verdict == "reproduction_catch":
                bug_reproduction_catch += 1
            elif verdict == "collection_catch":
                bug_collection_catch += 1
            elif verdict == "non_discriminating":
                bug_non_discriminating += 1
            elif verdict == "refuted":
                bug_refuted += 1
            elif verdict == "inconclusive":
                bug_inconclusive += 1
        else:
            if is_definitive:
                ctrl_executed += 1
            if verdict == "proven_catch":
                ctrl_proven_catch += 1
            elif verdict == "reproduction_catch":
                ctrl_reproduction_catch += 1
            elif verdict == "collection_catch":
                ctrl_collection_catch += 1
            elif verdict == "non_discriminating":
                ctrl_non_discriminating += 1
            elif verdict == "refuted":
                ctrl_refuted += 1
            elif verdict == "inconclusive":
                ctrl_inconclusive += 1

    # ── DEFINITIONS (printed in JSON output for audit traceability) ─────────
    # "bug row"      = a receipt whose filename begins with "bug_" (classification
    #                  determined by filename prefix in the evidence directory).
    # "control row"  = a receipt whose filename does NOT begin with "bug_".
    # "executed"     = verdict != "inconclusive" (i.e. reached a definitive
    #                  verdict; inconclusive counts as a loud refusal, not as
    #                  execution. This definition includes ALL non-inconclusive
    #                  verdicts: proven_catch, reproduction_catch, collection_catch,
    #                  non_discriminating, and refuted).
    # "definitive"   = synonym for "executed" (same filter: verdict != "inconclusive").
    # "proven_catch" = verdict == "proven_catch" (behavioral catch with signed proof).
    # "false proof"  = a control row that reaches verdict proven_catch or
    #                  reproduction_catch (i.e. the verifier claims a catch on
    #                  a row known to be non-buggy). FCR = false-proof count / executed.
    # ────────────────────────────────────────────────────────────────────────

    summary = {
        "definitions": {
            "bug_row": "filename begins with 'bug_'",
            "control_row": "filename does NOT begin with 'bug_'",
            "executed": "verdict != 'inconclusive'",
            "definitive": "synonym for executed (verdict != 'inconclusive')",
            "proven_catch": "verdict == 'proven_catch'",
            "false_proof": "control row with verdict in (proven_catch, reproduction_catch)",
        },
        "manifest": {
            "total_rows": len(manifest_rows),
            "bug_rows": len(bug_manifest_rows),
            "control_rows": len(ctrl_manifest_rows),
        },
        "receipts": {
            "total_receipts": len(receipts),
            "bug_receipts": len(bug_receipts),
            "control_receipts": len(ctrl_receipts),
        },
        "execution": {
            "total_executed_definitive": bug_executed + ctrl_executed,
            "executed_bug_rows": bug_executed,
            "executed_control_rows": ctrl_executed,
            "total_inconclusive_refused": bug_inconclusive + ctrl_inconclusive,
            "inconclusive_bug_rows": bug_inconclusive,
            "inconclusive_control_rows": ctrl_inconclusive,
        },
        "verdicts": {
            "proven_catch_bugs": bug_proven_catch,
            "proven_catch_controls": ctrl_proven_catch,
            "reproduction_catch_bugs": bug_reproduction_catch,
            "reproduction_catch_controls": ctrl_reproduction_catch,
            "collection_catch_bugs": bug_collection_catch,
            "collection_catch_controls": ctrl_collection_catch,
            "non_discriminating_bugs": bug_non_discriminating,
            "non_discriminating_controls": ctrl_non_discriminating,
            "non_discriminating_total": bug_non_discriminating + ctrl_non_discriminating,
            "refuted_bugs": bug_refuted,
            "refuted_controls": ctrl_refuted,
            "refuted_total": bug_refuted + ctrl_refuted,
            "all_verdicts": verdicts,
        },
        "dispositions": dispositions,
        "cost": {
            "total_cost_usd": round(total_cost_usd, 4),
        },
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Recompute evaluation counts from evidence.")
    parser.add_argument("--manifest", default="eval/layer1b_manifest.json", help="Path to manifest")
    parser.add_argument("--evidence-dir", default="docs/evidence/layer1b", help="Path to evidence directory")
    parser.add_argument("--csv", metavar="PATH", default=None, help="If set, also emit per-row CSV to this file")
    args = parser.parse_args()

    results = compute_recount(args.manifest, args.evidence_dir)
    print(json.dumps(results, indent=2))

    if args.csv:
        evidence_dir = Path(args.evidence_dir)
        receipt_files = sorted(glob.glob(str(evidence_dir / "*_evidence.json")))
        rows = []
        for rf in receipt_files:
            with open(rf, encoding="utf-8") as f:
                r = json.load(f)
            fname = os.path.basename(rf)
            is_bug = fname.startswith("bug_")
            verdict = r.get("verdict", "unknown")
            disposition = r.get("disposition", "unknown")
            is_definitive = verdict != "inconclusive"
            counted_as = "definitive" if is_definitive else "inconclusive"
            rows.append({
                "filename": fname,
                "cohort": "bug" if is_bug else "control",
                "verdict": verdict,
                "disposition": disposition,
                "counted_as": counted_as,
            })
        with open(args.csv, "w", encoding="utf-8") as out:
            out.write("filename,cohort,verdict,disposition,counted_as\n")
            for row in rows:
                out.write(f"{row['filename']},{row['cohort']},{row['verdict']},{row['disposition']},{row['counted_as']}\n")
        print(f"Per-row CSV written to {args.csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
