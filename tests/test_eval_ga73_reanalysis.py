"""Trusted, offline evaluation tests: no model calls or corpus execution."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path

try:
    import pytest
except ImportError:
    raise unittest.SkipTest("evaluation fixture suite requires pytest") from None

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ga73_reanalysis", ROOT / "eval/ga73_reanalysis.py")
assert SPEC and SPEC.loader
REANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REANALYSIS)


def test_frozen_mechanical_counts_and_scope():
    result = REANALYSIS.build(ROOT)["reanalysis.json"]
    bugs, click = result["cohorts"]["bugs"], result["cohorts"]["click"]
    assert (bugs["attempted"], bugs["response_bearing"]["numerator"],
            bugs["received_responses"], bugs["mechanically_caught_rows"]["numerator"],
            bugs["rows_with_reports"]["numerator"], bugs["candidate_reports"]) == (
                25, 22, 78, 16, 12, 13)
    assert (click["attempted"], click["response_bearing"]["numerator"],
            click["received_responses"], click["mechanically_caught_rows"]["numerator"],
            click["candidate_reports"], click["no_call_proofs"]) == (40, 40, 113, 11, 0, 20)
    assert click["mechanically_catching_candidates"] == 16
    assert bugs["mechanically_catching_candidates"] == 20
    assert bugs["conditional_mechanical_catch_rate"]["numerator"] == 16
    assert bugs["conditional_mechanical_catch_rate"]["denominator"] == 22
    assert click["paired_execution_rows"]["numerator"] == 12
    assert click["execution_screen"]["head_collection_failure_rate"]["denominator"] == 24
    assert bugs["execution_screen"]["head_collection_failure_rate"]["denominator"] == 38
    assert result["qualification_scope"] == "limited_response_and_collection_screening"
    assert result["independent_labels"] == "absent"
    assert result["runner_identity"] == "not_explicitly_archived"
    assert result["suppressed_candidate_review_material"] == "incomplete"
    assert result["cost_scope"] == "received_response_credit_debits_only"
    assert not result["ga_ready"]
    for field in ("adjudicated_fpr", "adjudicated_defect_recall",
                  "surfaced_claim_precision", "total_reconciled_provider_usd"):
        assert result[field] is None


def test_credit_precision_and_denominators():
    cohorts = REANALYSIS.build(ROOT)["reanalysis.json"]["cohorts"]
    assert cohorts["click"]["credit_debits"]["received_response_credit_debits_usd"] == "0.101980935540"
    assert cohorts["bugs"]["credit_debits"]["received_response_credit_debits_usd"] == "0.076117402230"
    assert cohorts["bugs"]["credit_debits"]["usd_per_attempted"] == "0.0030446960892"
    assert cohorts["bugs"]["credit_debits"]["response_bearing_denominator"] == 22
    assert cohorts["click"]["credit_debits"]["usd_per_attempted"] == "0.0025495233885"


def test_declines_do_not_dilute_collection_failures():
    rows = [{"disposition": "model_declined", "base_outcome": "", "head_outcome": ""}] * 49
    rows += [{"disposition": "head_uncollectable", "base_outcome": "", "head_outcome": "error"}] * 10
    rows += [{"disposition": "head_failed_base_failed_latent",
              "base_outcome": "fail", "head_outcome": "fail"}]
    # The historical pooled gate passed 10/60 plus any both-fail pair.
    assert 10 / len(rows) < 0.2
    result = REANALYSIS.execution_screen(rows)
    assert result["head_collection_failure_rate"]["denominator"] == 11
    assert result["head_collection_failure_rate"]["numerator"] == 10
    assert result["head_collection_screen"] == "at_or_above_20_percent"


def test_no_execution_is_not_assessed():
    result = REANALYSIS.execution_screen([{"disposition": "model_declined"}])
    assert result["head_collection_screen"] == "not_assessed"
    assert result["head_collection_failure_rate"]["rate"] is None


def test_uncollectable_without_outcomes_is_not_silently_excluded():
    with pytest.raises(ValueError, match="oracle-entry"):
        REANALYSIS.execution_screen([{"disposition": "head_uncollectable"}])


def test_packet_is_template_only_complete_and_blinded():
    output = REANALYSIS.build(ROOT)
    packet, key = output["reviewer-template.json"], output["custodian-key.json"]
    assert packet["blinding"] == "public_template_not_actually_blinded"
    assert key["distribution"] == "public_reference_mapping_not_private_custody"
    assert len(packet["cases"]) == 116
    assert len(key["typed_outcomes"]) == 159
    assert len({r["case_id"] for r in packet["cases"]}) == 116
    assert {r["case_id"] for r in packet["cases"]} == {r["case_id"] for r in key["case_mapping"]}
    reviewer_text = json.dumps(packet)
    for forbidden in ("assessor_verdict", "assessor_confidence", "real_regression",
                      "intended_change", "project", "bug_id", "pr_number",
                      "failure_excerpt", "json_pointer", "source_path"):
        assert forbidden not in reviewer_text
    assert all(r["review_status"] == "not_started" and r["reviewer_id"] is None
               and r["assertion_validity"] is None for r in packet["cases"])
    assert output["reanalysis.json"]["packet_counts"] == {
        "population": 80, "candidate_assertion": 36}


def test_raw_baseline_hashes_unchanged():
    baseline = json.loads((ROOT / REANALYSIS.OUT / "baseline-sha256.json").read_text(encoding="utf-8"))
    REANALYSIS.verify_baseline(ROOT, baseline)
    damaged = copy.deepcopy(baseline)
    damaged["files"][REANALYSIS.INPUTS["click"].as_posix()] = "0" * 64
    with pytest.raises(ValueError, match="immutable raw baseline changed"):
        REANALYSIS.verify_baseline(ROOT, damaged)


def test_billing_contract_rejects_malformed_and_noncredit_accounting():
    archive = json.loads((ROOT / REANALYSIS.INPUTS["click"]).read_text(encoding="utf-8"))
    rows = archive["results"]
    rows[0]["provider_billing"]["provider_paid_with"] = ["energy"]
    with pytest.raises(ValueError, match="billing contract"):
        REANALYSIS.credit_totals(rows, "1.1355")
    rows[0]["provider_billing"]["provider_paid_with"] = ["credits"]
    rows[0]["provider_billing"]["provider_credit_debit_eur"] = "NaN"
    with pytest.raises(ValueError, match="invalid credit debit"):
        REANALYSIS.credit_totals(rows, "1.1355")


def test_deterministic_checked_in_outputs():
    for name, value in REANALYSIS.build(ROOT).items():
        assert (ROOT / REANALYSIS.OUT / name).read_text(encoding="utf-8") == (
            json.dumps(value, indent=2, sort_keys=True) + "\n")


def test_cost_contract_has_no_fabricated_dispatches_or_reconciliation():
    contract = json.loads((ROOT / REANALYSIS.OUT / "cost-reconciliation-contract.json").read_text(encoding="utf-8"))
    assert contract["events"] == []
    assert contract["owner_supplied_statement"] is None
    assert contract["total_reconciled_provider_usd"] is None
    assert "assessor" in contract["stage_enum"]
    assert "dispatch_id" in contract["event_required_fields"]
    assert "content_parse_status" in contract["event_required_fields"]
    assert "provider_request_id" in contract["event_required_fields"]