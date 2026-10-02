"""Offline synthetic validator tests, NOT independent human review or billing evidence."""
from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import patch

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover
    import unittest
    raise unittest.SkipTest("requires pytest; exercised by the pytest CI matrix") from exc

from eval import ga73_acceptance as acceptance
from eval.ga73_reanalysis import INPUTS, OUT
from scripts import launch_gate


def ref(root, path, value):
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value))
    return {"path": path, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}


@pytest.fixture
def synthetic(tmp_path):
    """Small fake cohort, local only. All human/billing records are unit-test fixtures."""
    candidate = "def test_synthetic(): assert True\n"
    digest = hashlib.sha256(candidate.encode()).hexdigest()
    bugs = {"bug_results": [{"reported": 1, "model_requests": 1,
        "provider_billing": {"provider_credit_debit_eur": "0.2"},
        "telemetry": [{"disposition": "catching", "candidate_source_sha256": digest}]}],
        "fx_usd_per_eur": "1"}
    click = {"results": [{"pr_number": 1, "reported": 0, "model_requests": 1,
        "provider_billing": {"provider_credit_debit_eur": "0.3"}, "telemetry": []}],
        "manifest": {"python_sampling_frame": [{"pr_number": 1}, {"pr_number": 2}]},
        "fx_usd_per_eur": "1"}
    sources = {kind: ref(tmp_path, path.as_posix(), archive)
               for kind, path, archive in (("bugs", INPUTS["bugs"], bugs),
                                           ("click", INPUTS["click"], click))}
    ref(tmp_path, (OUT / "baseline-sha256.json").as_posix(),
        {"files": {r["path"]: r["sha256"] for r in sources.values()}})
    cases = [{"case_id": "bug", "review_type": "population"},
             {"case_id": "pr", "review_type": "population"},
             {"case_id": "skip", "review_type": "population"},
             {"case_id": "candidate", "review_type": "candidate_assertion"}]
    mapping = [{"case_id": case, "source": INPUTS[kind].as_posix(), "json_pointer": pointer}
               for case, kind, pointer in (("bug", "bugs", "/bug_results/0"),
                   ("pr", "click", "/manifest/python_sampling_frame/0"),
                   ("skip", "click", "/manifest/python_sampling_frame/1"),
                   ("candidate", "bugs", "/bug_results/0/telemetry/0"))]
    material = ref(tmp_path, "candidate.json", {"case_id": "candidate", "candidate_bytes": candidate,
        "candidate_sha256": digest, "source_sha256": sources["bugs"]["sha256"],
        "json_pointer": "/bug_results/0/telemetry/0", "runner": "pytest",
        "base_outcome": "pass", "head_outcome": "fail"})
    evidence = ref(tmp_path, "synthetic-review-not-human-evidence.json", {"synthetic": True})
    labels = {"reviewer_kind": "human", "reviewer_id": "SYNTHETIC-test-reviewer",
        "independent": True, "blinded": True, "private_custody": True,
        "labels_locked_before_unblinding": True,
        "cases": [{"case_id": c, "ground_truth": "defect" if c == "bug" else "clean",
                   "rationale": "SYNTHETIC fixture only", "evidence": evidence}
                  for c in ("bug", "pr", "skip")] + [{"case_id": "candidate",
            "assertion_valid": True, "change_intent": "regression", "defect_correspondence": True,
            "surfaced": True, "rationale": "SYNTHETIC fixture only", "evidence": evidence,
            "material": material}]}
    labels["attestation"] = ref(tmp_path, "attestation.json", {
        **{k: labels[k] for k in ("reviewer_kind", "reviewer_id", "independent", "blinded",
            "private_custody", "labels_locked_before_unblinding")}, "sources": sources,
        "custodian_id": "SYNTHETIC-other-person",
        "case_records_sha256": acceptance.case_records_digest(labels["cases"])})
    events = [{"dispatch_id": d, "target_case_id": target, "stage": stage,
        "transport_status": status, "provider_request_id": "SYNTHETIC-" + d,
        "statement_line_id": "line-" + d, "amount_usd": amount}
        for d, target, stage, status, amount in (("d1", "bug", "generator", "response_received", "0.2"),
            ("d2", "pr", "assessor", "response_received", "0.3"),
            ("d3", "pr", "generator", "timeout", "0.1"))]
    lines = [{"line_id": e["statement_line_id"], "dispatch_ids": [e["dispatch_id"]],
              "amount_usd": e["amount_usd"]} for e in events]
    cost = {"currency": "USD", "complete": True, "provider_total_usd": "0.6", "ci_total_usd": "2",
        "ci_allocation_usd": {"bugs": "1", "click": "1"}, "dispatches": events, "statement_lines": lines}
    cost["statement"] = ref(tmp_path, "statement.json", {"currency": "USD", "lines": lines,
        "opening_balance": "10", "closing_balance": "9.4", "topups": "0", "refunds": "0", "other_debits": "0"})
    cost["dispatch_inventory"] = ref(tmp_path, "inventory.json", {"sources": sources, "complete": True, "dispatches": events})
    cost["ci_receipt"] = ref(tmp_path, "ci.json", {"sources": sources, "currency": "USD", "total_usd": "2",
        "allocation_usd": cost["ci_allocation_usd"]})
    cost["reconciliation_attestation"] = ref(tmp_path, "owner.json", {"sources": sources, "scope_complete": True,
        "owner_id": "SYNTHETIC-owner"})
    output = {"reviewer-template.json": {"cases": cases}, "custodian-key.json": {"case_mapping": mapping}}
    manifest = {"schema_version": 1, "sources": sources, "labels": labels, "cost": cost}
    with patch.object(acceptance, "build", return_value=output):
        yield tmp_path, manifest


def test_real_checkpoint_stays_blocked_null():
    result = acceptance.load_acceptance()
    assert result["ok"] and result["status"] == "blocked" and not result["ga_ready"]
    assert all(value is None for value in result["metrics"].values())


def test_deleting_static_blockers_is_insufficient():
    good = {"technical": {"ok": True}}
    assert launch_gate.build_report(good, [])["decision"] == "NO_GO"
    result = launch_gate.build_report(good, [], acceptance.load_acceptance())
    assert result["decision"] == "GO_LAUNCH_NOT_GA"
    assert not result["ga_ready"]


def test_missing_invalid_and_duplicate_json_fail_closed(tmp_path):
    assert not acceptance.load_acceptance(tmp_path / "absent.json")["ok"]
    for text in ('{"schema_version":1,"schema_version":1}', '{"x":NaN}', '{"x":Infinity}',
                 '{"x":-Infinity}', '{"nested":{"x":1,"x":2}}', '[]', 'null', '{'):
        path = tmp_path / "bad.json"
        path.write_text(text)
        assert not acceptance.load_acceptance(path)["ok"]
        with pytest.raises(ValueError):
            if text not in ('[]', 'null'):
                acceptance.strict_json(text)
            else:
                raise ValueError("not an object")


def test_synthetic_complete_evidence_recomputes_semantic_denominators(synthetic):
    root, manifest = synthetic
    result = acceptance.validate(manifest, root)
    assert result["ok"], result
    assert result["status"] == "accepted"
    assert not result["ga_ready"]
    assert result["metrics"]["adjudicated_fpr"] == {"numerator": 0, "denominator": 2, "rate": "0"}
    assert result["metrics"]["adjudicated_defect_recall"] == {"numerator": 1, "denominator": 1, "rate": "1"}
    assert result["metrics"]["all_in_total_usd"] == "2.6"
    assert result["metrics"]["all_in_usd_per_attempted"]["click"]["mean_usd"] == "1.4"
    assert result["blockers"] == [
        "all_in_cost_not_below_launch_threshold",
        "representative_default_product_scope_missing",
    ]
    assert launch_gate.build_report(
        {"technical": {"ok": True}}, [], result
    )["decision"] == "GO_LAUNCH_NOT_GA"
    assert launch_gate.build_report({"technical": {"ok": True}}, [{"issue": 73}], result)["decision"] == "GO_LAUNCH_NOT_GA"


@pytest.mark.parametrize("section,field,value", [
    ("labels", "reviewer_kind", "agent"), ("labels", "independent", "true"),
    ("labels", "blinded", False), ("labels", "private_custody", False),
    ("labels", "labels_locked_before_unblinding", False),
    ("cost", "complete", 1), ("cost", "currency", "EUR"),
    ("cost", "provider_total_usd", "NaN"), ("cost", "ci_total_usd", "Infinity"),
    ("cost", "provider_total_usd", "0.1"), ("cost", "ci_total_usd", -1),
])
def test_wrong_semantics_cannot_pass(synthetic, section, field, value):
    root, manifest = synthetic
    manifest[section][field] = value
    assert not acceptance.validate(manifest, root)["ok"]


def test_wrong_source_missing_population_duplicate_and_zero_denominators(synthetic):
    root, good = synthetic
    mutations = []
    bad = copy.deepcopy(good)
    bad["sources"]["bugs"]["sha256"] = "0" * 64
    mutations.append(bad)
    bad = copy.deepcopy(good)
    bad["labels"]["cases"].pop(0)
    mutations.append(bad)
    bad = copy.deepcopy(good)
    bad["labels"]["cases"][1] = bad["labels"]["cases"][0]
    mutations.append(bad)
    bad = copy.deepcopy(good)
    bad["labels"]["cases"][0]["ground_truth"] = "clean"
    mutations.append(bad)
    bad = copy.deepcopy(good)
    bad["labels"]["cases"][-1]["surfaced"] = False
    mutations.append(bad)
    for manifest in mutations:
        assert not acceptance.validate(manifest, root)["ok"]


def test_unknown_debits_duplicate_dispatches_and_unallocated_lines_refuse(synthetic):
    root, good = synthetic
    for field, value in (("dispatches", good["cost"]["dispatches"] * 2),
                         ("statement_lines", good["cost"]["statement_lines"] * 2),
                         ("ci_allocation_usd", {"bugs": "2", "click": "1"})):
        bad = copy.deepcopy(good)
        bad["cost"][field] = value
        assert not acceptance.validate(bad, root)["ok"]
    bad = copy.deepcopy(good)
    bad["cost"]["dispatches"][2]["amount_usd"] = None
    assert not acceptance.validate(bad, root)["ok"]


def test_candidate_material_and_human_attestation_are_bound(synthetic):
    root, good = synthetic
    bad = copy.deepcopy(good)
    candidate = bad["labels"]["cases"][-1]
    doc = json.loads((root / candidate["material"]["path"]).read_text())
    doc["source_sha256"] = "0" * 64
    candidate["material"] = ref(root, "unbound.json", doc)
    assert not acceptance.validate(bad, root)["ok"]
    bad = copy.deepcopy(good)
    attestation = json.loads((root / bad["labels"]["attestation"]["path"]).read_text())
    attestation["reviewer_id"] = "different"
    bad["labels"]["attestation"] = ref(root, "wrong-reviewer.json", attestation)
    assert not acceptance.validate(bad, root)["ok"]


def test_invalid_acceptance_blocks_otherwise_green_launch():
    for result in (None, {"ok": False, "ga_ready": True}, {"ok": "true", "ga_ready": True}):
        assert launch_gate.build_report({"technical": {"ok": True}}, [], result)["decision"] == "NO_GO"


def test_hash_bound_cross_target_underallocation_refuses(synthetic):
    root, manifest = synthetic
    cost = manifest["cost"]
    # Preserve global 0.6 total while moving one target's observed debit away.
    cost["dispatches"][0]["amount_usd"] = "0.0"
    cost["dispatches"][1]["amount_usd"] = "0.5"
    cost["statement_lines"][0]["amount_usd"] = "0.0"
    cost["statement_lines"][1]["amount_usd"] = "0.5"
    statement = json.loads((root / cost["statement"]["path"]).read_text())
    statement["lines"] = cost["statement_lines"]
    cost["statement"] = ref(root, "reallocated-statement.json", statement)
    inventory = json.loads((root / cost["dispatch_inventory"]["path"]).read_text())
    inventory["dispatches"] = cost["dispatches"]
    cost["dispatch_inventory"] = ref(root, "reallocated-inventory.json", inventory)
    assert not acceptance.validate(manifest, root)["ok"]


def test_plain_dict_cannot_impersonate_validator_result(synthetic):
    root, manifest = synthetic
    genuine = acceptance.validate(manifest, root)
    assert genuine["ok"] and not genuine["ga_ready"]
    plain_copy = json.loads(json.dumps(genuine))
    good = {"technical": {"ok": True}}
    assert launch_gate.build_report(good, [], plain_copy)["decision"] == "NO_GO"
    assert not launch_gate.derive_ga_ready([], plain_copy)
    forged = {"ok": True, "status": "accepted", "ga_ready": True}
    assert launch_gate.build_report(good, [], forged)["decision"] == "NO_GO"


@pytest.mark.parametrize(
    "recall,fpr,bug_cost,click_cost,scope,expected",
    [
        ("0.25", "0.09", "0.99", "0.99", "representative_default_product",
         ["defect_recall_not_above_launch_threshold"]),
        ("0.26", "0.10", "0.99", "0.99", "representative_default_product",
         ["false_positive_rate_not_below_launch_threshold"]),
        ("0.26", "0.09", "1.00", "0.99", "representative_default_product",
         ["all_in_cost_not_below_launch_threshold"]),
        ("0.26", "0.09", "0.99", "0.99", "frozen_conditional_cohorts_only",
         ["representative_default_product_scope_missing"]),
        ("0.26", "0.09", "0.99", "0.99", "representative_default_product", []),
    ],
)
def test_policy_threshold_boundaries_are_strict(
    recall, fpr, bug_cost, click_cost, scope, expected
):
    metrics = {
        "adjudicated_defect_recall": {"rate": recall},
        "adjudicated_fpr": {"rate": fpr},
        "all_in_usd_per_attempted": {
            "bugs": {"mean_usd": bug_cost},
            "click": {"mean_usd": click_cost},
        },
    }
    assert acceptance._policy_blockers(metrics, scope) == expected


def test_complete_v1_below_thresholds_is_scope_blocked_end_to_end(
    synthetic
):
    root, manifest = synthetic
    cost = manifest["cost"]
    cost["ci_total_usd"] = "0.4"
    cost["ci_allocation_usd"] = {"bugs": "0.2", "click": "0.2"}
    cost["ci_receipt"] = ref(root, "ci-below-threshold.json", {
        "sources": manifest["sources"],
        "currency": "USD",
        "total_usd": "0.4",
        "allocation_usd": cost["ci_allocation_usd"],
    })
    result = acceptance.validate(manifest, root)
    assert result["ok"] and result["status"] == "accepted"
    assert result["blockers"] == [
        "representative_default_product_scope_missing",
    ]
    assert not result["ga_ready"]
    assert launch_gate.build_report(
        {"technical": {"ok": True}}, [], result
    )["decision"] == "GO_LAUNCH_NOT_GA"


def test_locked_decision_cannot_change_without_new_attestation(synthetic):
    root, manifest = synthetic
    assert acceptance.validate(manifest, root)["ok"]
    manifest["labels"]["cases"][-1]["assertion_valid"] = False
    assert not acceptance.validate(manifest, root)["ok"]


def test_case_lock_is_order_independent_and_all_fields_sensitive(synthetic):
    root, manifest = synthetic
    manifest["labels"]["cases"].reverse()
    assert acceptance.validate(manifest, root)["ok"]
    manifest["labels"]["cases"][0]["rationale"] = "changed after lock"
    assert not acceptance.validate(manifest, root)["ok"]
