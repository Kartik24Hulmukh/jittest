"""Read-only, offline reanalysis of retained GA73 archives; never imports corpus code."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import Counter
from decimal import Decimal
from pathlib import Path

RAW = Path("docs/evidence/ga73-20260930")
OUT = Path("docs/evidence/ga73-reanalysis-20260930")
INPUTS = {
    "click": RAW / "ci-pr-qualified/ga73-pr-pilot.json",
    "bugs": RAW / "ci-default-bugs/ga73-default-bugs.json",
}
FX = {
    "click": RAW / "ci-pr-qualified/ga73-canary-fx.xml",
    "bugs": RAW / "ci-default-bugs/ga73-fx.xml",
}
SCOPE = {
    "qualification_scope": "limited_response_and_collection_screening",
    "independent_labels": "absent",
    "runner_identity": "not_explicitly_archived",
    "suppressed_candidate_review_material": "incomplete",
    "cost_scope": "received_response_credit_debits_only",
    "ga_ready": False,
    "adjudicated_fpr": None,
    "adjudicated_defect_recall": None,
    "surfaced_claim_precision": None,
    "total_reconciled_provider_usd": None,
    "ci_runtime_expense_usd": None,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def metric(numerator: int, denominator: int, population: str) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "population": population,
        "rate": str(Decimal(numerator) / denominator) if denominator else None,
    }


def execution_screen(telemetry: list[dict]) -> dict:
    """Do not dilute oracle-entry collection failures with generation refusals."""
    entering = [
        t for t in telemetry if t.get("head_outcome") or t.get("base_outcome")
    ]
    pairs = [
        t for t in entering
        if t.get("head_outcome") in ("pass", "fail")
        and t.get("base_outcome") in ("pass", "fail")
    ]
    failures = sum(
        str(t.get("disposition", "")).startswith("head_uncollectable")
        for t in telemetry
    )
    # Refuse inconsistent rows rather than excluding an uncollectable from the denominator.
    if failures > sum(
        str(t.get("disposition", "")).startswith("head_uncollectable")
        for t in entering
    ):
        raise ValueError("uncollectable candidate lacks oracle-entry outcomes")
    return {
        "telemetry_rows": len(telemetry),
        "oracle_entering_candidates": len(entering),
        "no_recorded_execution_outcome": len(telemetry) - len(entering),
        "head_collection_failure_rate": metric(
            failures, len(entering), "candidates with any recorded execution outcome"
        ),
        "head_collection_screen": (
            "not_assessed" if not entering
            else "below_20_percent" if Decimal(failures) / len(entering) < Decimal("0.2")
            else "at_or_above_20_percent"
        ),
        "paired_pass_fail_outcomes": len(pairs),
        "unpaired_or_partial_outcomes": len(entering) - len(pairs),
        "outcome_pairs": {
            f"{base or 'not_recorded'}|{head or 'not_recorded'}": n
            for (base, head), n in sorted(Counter(
                (t.get("base_outcome", ""), t.get("head_outcome", ""))
                for t in telemetry
            ).items())
        },
        "interpretation": "Descriptive screening only; not runner or assertion validity.",
    }


def credit_totals(rows: list[dict], fx: str) -> dict:
    received = [r for r in rows if r["model_requests"] > 0]
    bills = [r["provider_billing"] for r in received]
    if not all(
        b and b["provider_billing_complete"] and b["provider_paid_with"] == ["credits"]
        and b["provider_response_count"] == r["model_requests"]
        for r, b in zip(received, bills, strict=True)
    ):
        raise ValueError("received-response billing contract mismatch")
    values = [b["provider_credit_debit_eur"] for b in bills]
    amounts = [Decimal(v) for v in values]
    if not all(v.is_finite() and v >= 0 for v in amounts):
        raise ValueError("invalid credit debit")
    eur = sum(amounts, Decimal(0))
    # Independent scaled-integer sum checks the Decimal path.
    scale = max((len(v.partition(".")[2]) for v in values), default=0)
    units = sum(int(v.replace(".", "")) * 10 ** (scale - len(v.partition(".")[2]))
                for v in values)
    if Decimal(units).scaleb(-scale) != eur:
        raise ValueError("independent billing sum mismatch")
    rate = Decimal(fx)
    if not rate.is_finite() or rate <= 0:
        raise ValueError("invalid FX")
    usd = eur * rate
    return {
        "received_response_credit_debits_eur": str(eur),
        "fx_usd_per_eur": fx,
        "received_response_credit_debits_usd": str(usd),
        "usd_per_attempted": str(usd / len(rows)) if rows else None,
        "attempted_denominator": len(rows),
        "usd_per_response_bearing": str(usd / len(received)) if received else None,
        "response_bearing_denominator": len(received),
        "billing_completeness": "complete_only_for_responses_reaching_archived_accounting",
        "unobserved_debits": "unknown_not_zero",
        "wallet_invoice_reconciled": False,
    }


def cohort_summary(kind: str, archive: dict) -> dict:
    rows = archive["results" if kind == "click" else "bug_results"]
    ts = [t for r in rows for t in r["telemetry"]]
    catches = [t for t in ts if t["disposition"] == "catching"]
    caught_rows = sum(any(t["disposition"] == "catching" for t in r["telemetry"])
                      for r in rows)
    # Independent row status/count paths preserve the historical mechanical baseline.
    if kind == "bugs" and (
        caught_rows != sum(r["status"] == "caught" for r in rows)
        or len(catches) != sum(r["catching_candidates"] for r in rows)
    ):
        raise ValueError("mechanical counts disagree")
    screen = execution_screen(ts)
    return {
        "attempted": len(rows),
        "response_bearing": metric(sum(r["model_requests"] > 0 for r in rows),
                                   len(rows), "all attempted cohort rows"),
        "received_responses": sum(r["model_requests"] for r in rows),
        "mechanically_caught_rows": metric(caught_rows, len(rows), "all attempted cohort rows"),
        "conditional_mechanical_catch_rate": metric(
            sum(r["model_requests"] > 0 and any(t["disposition"] == "catching"
                for t in r["telemetry"]) for r in rows),
            sum(r["model_requests"] > 0 for r in rows), "response-bearing cohort rows only"),
        "mechanically_catching_candidates": len(catches),
        "rows_with_reports": metric(sum(r["reported"] > 0 for r in rows),
                                   len(rows), "all attempted cohort rows"),
        "candidate_reports": sum(r["reported"] for r in rows),
        "paired_execution_rows": metric(sum(any(
            t.get("base_outcome") in ("pass", "fail")
            and t.get("head_outcome") in ("pass", "fail")
            for t in r["telemetry"]) for r in rows), len(rows), "all attempted cohort rows"),
        "dispositions": dict(sorted(Counter(t["disposition"] for t in ts).items())),
        "catching_model_assessments_not_human_labels": dict(sorted(Counter(
            t["assessor_verdict"] for t in catches).items())),
        "execution_screen": screen,
        "credit_debits": credit_totals(rows, archive["fx_usd_per_eur"]),
        "legacy_collection_qualified": archive["collection_qualified"],
        "legacy_qualification_not_semantic_validation": True,
    }


def blank_review(case_id: str, kind: str) -> dict:
    """No cohort tags, model verdicts, confidence, source pointers or trigger tests."""
    return {
        "case_id": case_id,
        "review_type": kind,
        "packet_status": "template_only_unadjudicatable_from_retained_archive",
        "material": {
            "exact_candidate_bytes": None,
            "candidate_sha256": None,
            "neutral_base_head_tree_ids": None,
            "supported_contract_and_docs": None,
            "execution_and_rerun_receipts": None,
        },
        "reviewer_id": None,
        "independence_attestation": None,
        "assertion_validity": None,
        "change_intent": None,
        "population_ground_truth": None,
        "report_usefulness": None,
        "rationale_and_evidence_refs": [],
        "review_status": "not_started",
    }


def build_packet(archives: dict, input_hashes: dict) -> tuple[dict, dict]:
    reviewer, key, failures = [], [], []

    def add(kind: str, source: str, pointer: str) -> None:
        case_id = sha256(f"ga73-v1:{input_hashes[source]}:{pointer}".encode())[:24]
        reviewer.append(blank_review(case_id, kind))
        key.append({"case_id": case_id, "source": source, "json_pointer": pointer})

    for cohort, archive in archives.items():
        source = INPUTS[cohort].as_posix()
        row_key = "results" if cohort == "click" else "bug_results"
        # Population review includes nonreports AND static risk skips.
        if cohort == "click":
            for i, _ in enumerate(archive["manifest"]["python_sampling_frame"]):
                add("population", source, f"/manifest/python_sampling_frame/{i}")
        else:
            for i, _ in enumerate(archive[row_key]):
                add("population", source, f"/{row_key}/{i}")
        for i, row in enumerate(archive[row_key]):
            for j, t in enumerate(row["telemetry"]):
                pointer = f"/{row_key}/{i}/telemetry/{j}"
                failures.append({
                    "source": source, "json_pointer": pointer,
                    "disposition": t["disposition"],
                    "base_outcome": t["base_outcome"], "head_outcome": t["head_outcome"],
                })
                if t["disposition"] == "catching":
                    add("candidate_assertion", source, pointer)
    return (
        {"schema_version": 1, "blinding": "public_template_not_actually_blinded",
         "custody_warning": "Public mapping permits unblinding; real review requires separate private custody.",
         "cases": sorted(reviewer, key=lambda r: r["case_id"])},
        {"schema_version": 1, "distribution": "public_reference_mapping_not_private_custody",
         "custody_warning": "Not a secret key; do not reuse these publicly mapped IDs for real blinded review.",
         "input_sha256": input_hashes, "case_mapping": key,
         "typed_outcomes": failures,
         "benchmark_correspondence_second_phase": {
             "labels": None, "status": "not_started",
             "instruction": "After locking phase-one labels, separately assess defect-trigger correspondence."
         }},
    )


def verify_baseline(root: Path, baseline: dict) -> None:
    # RESULTS wording is intentionally changed; its pre-edit hash remains in the manifest.
    for name, expected in baseline["files"].items():
        if name.startswith(RAW.as_posix() + "/") and sha256((root / name).read_bytes()) != expected:
            raise ValueError(f"immutable raw baseline changed: {name}")


def build(root: Path) -> dict[str, dict]:
    baseline = json.loads((root / OUT / "baseline-sha256.json").read_text(encoding="utf-8"))
    verify_baseline(root, baseline)
    hashes = {p.as_posix(): sha256((root / p).read_bytes())
              for p in [*INPUTS.values(), *FX.values()]}
    archives = {k: json.loads((root / p).read_text(encoding="utf-8")) for k, p in INPUTS.items()}
    for k, p in FX.items():
        rate = next(el.attrib["rate"] for el in ET.fromstring((root / p).read_bytes()).iter()
                    if el.attrib.get("currency") == "USD")
        if Decimal(rate) != Decimal(archives[k]["fx_usd_per_eur"]):
            raise ValueError("archived FX differs from raw ECB input")
    summaries = {k: cohort_summary(k, a) for k, a in archives.items()}
    click = archives["click"]
    pairs = click["manifest"]["pairs"]
    rows = click["results"]
    if len({(r["base"], r["head"]) for r in rows}) != len(rows):
        raise ValueError("duplicate applied pair")
    identities = {(p["base"], p["head"], p["pr_number"]) for p in pairs}
    if identities != {(r["base"], r["head"], r["pr_number"]) for r in rows}:
        raise ValueError("manifest/row identities differ")
    if not all(p["head"] == p["merge_sha"] for p in pairs):
        raise ValueError("not applied merge identities")
    proofs = click["no_call_proofs"]
    if not all(r["model_request_attempts"] == r["model_requests"] == r["reported"] == 0
               for r in proofs):
        raise ValueError("no-call proof violated")
    frame = click["manifest"]["python_sampling_frame"]
    skipped = click["manifest"]["risk_skipped_frame"]
    if (len({p["pr_number"] for p in frame}) != len(frame)
            or {p["pr_number"] for p in rows} & {p["pr_number"] for p in skipped}
            or len(frame) != len(rows) + len(skipped)
            or {p["pr_number"] for p in frame}
            != {p["pr_number"] for p in rows + skipped}):
        raise ValueError("sampling frame partition mismatch")
    summaries["click"].update({
        "screening_pr_report_rate": summaries["click"]["rows_with_reports"],
        "risk_eligibility": metric(len(rows), len(frame), "Python-changing PR sampling frame"),
        "static_risk_skips": len(skipped),
        "no_call_proofs": len(proofs),
        "legacy_screened_out_distinct_category": click["manifest"]["screened_out"],
        "legacy_proxy_fields": ["false_positive_rate", "publishable", "comments_per_100_prs"],
        "rule_of_three_upper_95_screening_only": str(Decimal(3) / len(rows)),
        "exact_one_sided_zero_event_upper_95_screening_only": 1 - 0.05 ** (1 / len(rows)),
        "bound_assumptions": "Independent common-rate sampling not demonstrated; not labeled FPR.",
        "catching_excerpts_with_minirunner": sum(
            "_minirunner" in t["failure_excerpt"] for r in rows for t in r["telemetry"]
            if t["disposition"] == "catching"),
        "generation_invocations_not_http_attempts": sum(r["model_request_attempts"] for r in rows),
        "manifest_identity_check": "matched_archived_applied_heads_not_new_git_parent_verification",
    })
    summaries["bugs"]["project_mix"] = dict(sorted(Counter(
        r["project"] for r in archives["bugs"]["bug_results"]).items()))
    reviewer, custodian = build_packet(archives, hashes)
    return {
        "reanalysis.json": {
            "schema_version": 1, "baseline_commit": baseline["baseline_commit"],
            "analysis_code_sha256": sha256((root / "eval/ga73_reanalysis.py").read_bytes()),
            "input_sha256": hashes, **SCOPE,
            "sampling_frame_type": "historical_sorted_bugs_and_conditional_single_project_prs",
            "label_status": "unadjudicated",
            "cohorts": summaries,
            "packet_counts": dict(Counter(r["review_type"] for r in reviewer["cases"])),
            "comparison_plan": {
                "disposition": "prose",
                "reason": "Audit contracts, not a comparative visualization; incompatible populations.",
            },
        },
        "reviewer-template.json": reviewer,
        "custodian-key.json": custodian,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="Verify deterministic outputs; write nothing.")
    args = parser.parse_args()
    for name, value in build(args.root).items():
        serialized = json.dumps(value, indent=2, sort_keys=True) + "\n"
        target = args.root / OUT / name
        if args.check:
            if target.read_text(encoding="utf-8") != serialized:
                raise ValueError(f"stale derived artifact: {name}")
        else:
            target.write_bytes(serialized.encode("utf-8"))
    print("GA73 reanalysis verified; GA remains unproven.")


if __name__ == "__main__":
    main()