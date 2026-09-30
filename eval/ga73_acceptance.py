"""Offline GA73 evidence acceptance. Attestations are evidence, not human verification."""
from __future__ import annotations

import argparse
import hashlib
import json
from decimal import Decimal
from pathlib import Path

from eval.ga73_reanalysis import INPUTS, OUT, build

ROOT = Path(__file__).resolve().parents[1]


class ValidatedAcceptance(dict):
    """Internal validator output, not a JSON declaration or Python security sandbox.

    Only validate() supplies this type on success. This distinguishes raw input
    dictionaries at the launch API; it cannot constrain malicious in-process code.
    """


def strict_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("nonfinite JSON number")

    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant,
                        parse_float=Decimal)
    return result


def case_records_digest(records):
    """Lock exact decisions and material references, independent of list ordering."""
    ordered = sorted(records, key=lambda record: record["case_id"])
    serialized = json.dumps(ordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _amount(value):
    _require(isinstance(value, str), "money must be a decimal string")
    number = Decimal(value)
    _require(number.is_finite() and number >= 0, "invalid monetary amount")
    return number


def _reference(root, ref):
    _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "invalid evidence reference")
    _require(isinstance(ref["path"], str) and isinstance(ref["sha256"], str), "invalid reference fields")
    path = (root / ref["path"]).resolve()
    _require(not Path(ref["path"]).is_absolute() and path.is_relative_to(root.resolve()),
             "evidence path must remain inside repository")
    _require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"],
             "evidence reference hash mismatch")


def blocked_checkpoint(root=ROOT):
    """Explicit null checkpoint; never fabricate labels, invoice or CI expense."""
    baseline = strict_json((root / OUT / "baseline-sha256.json").read_text())
    return {"schema_version": 1, "sources": {
        kind: {"path": path.as_posix(), "sha256": baseline["files"][path.as_posix()]}
        for kind, path in INPUTS.items()}, "labels": None, "cost": None}


def _labels(root, labels, packet, key, archives, sources):
    _require(isinstance(labels, dict), "labels must be an object or null")
    _require(labels.get("reviewer_kind") == "human" and labels.get("independent") is True
             and labels.get("blinded") is True and labels.get("labels_locked_before_unblinding") is True, "independent blinded human attestation required")
    _require(isinstance(labels.get("reviewer_id"), str) and labels["reviewer_id"].strip(),
             "reviewer identity required")
    _reference(root, labels.get("attestation"))
    attestation = strict_json((root / labels["attestation"]["path"]).read_text())
    _require(attestation.get("sources") == sources and all(
        attestation.get(field) == labels.get(field)
        for field in ("reviewer_id", "reviewer_kind", "independent", "blinded", "private_custody", "labels_locked_before_unblinding")),
        "human attestation source/identity mismatch")
    _require(isinstance(attestation.get("custodian_id"), str)
             and attestation["custodian_id"] and attestation["custodian_id"] != labels["reviewer_id"],
             "separate blinding custodian required")
    _require(labels.get("private_custody") is True, "public template is not blinded custody")
    records = labels.get("cases")
    _require(isinstance(records, list), "human cases missing")
    expected = {case["case_id"]: case["review_type"] for case in packet["cases"]}
    ids = [r.get("case_id") for r in records if isinstance(r, dict)]
    _require(len(ids) == len(records) == len(expected) and set(ids) == set(expected),
             "human labels must cover every population and catching assertion exactly once")
    _require(attestation.get("case_records_sha256") == case_records_digest(records),
             "locked human decision digest mismatch")
    mappings = {r["case_id"]: r for r in key["case_mapping"]}
    indexed = {}
    for row in records:
        case = row["case_id"]
        _reference(root, row.get("evidence"))
        _require(isinstance(row.get("rationale"), str) and row["rationale"].strip(), "human rationale required")
        if expected[case] == "population":
            _require(row.get("ground_truth") in ("clean", "defect"), "population label unresolved")
        else:
            _require(type(row.get("assertion_valid")) is bool and
                     row.get("change_intent") in ("intended", "regression") and
                     type(row.get("defect_correspondence")) is bool and type(row.get("surfaced")) is bool,
                     "candidate adjudication unresolved")
            # Source-bound material receipt must retain exact bytes and paired execution;
            # model verdicts and failure excerpts are not substitutes for those bytes.
            _reference(root, row.get("material"))
            material = strict_json((root / row["material"]["path"]).read_text())
            _require(material.get("case_id") == case and material.get("candidate_bytes")
                     and isinstance(material["candidate_bytes"], str), "exact candidate material missing")
            _require(material.get("candidate_sha256") == hashlib.sha256(
                material["candidate_bytes"].encode()).hexdigest(), "candidate digest mismatch")
            mapping = mappings[case]
            kind = "bugs" if mapping["source"] == INPUTS["bugs"].as_posix() else "click"
            parts = mapping["json_pointer"].split("/")
            archived = archives[kind][parts[1]][int(parts[2])][parts[3]][int(parts[4])]
            _require(material.get("source_sha256") == sources[kind]["sha256"]
                     and material.get("json_pointer") == mapping["json_pointer"]
                     and material["candidate_sha256"] == archived.get("candidate_source_sha256"),
                     "candidate archive binding mismatch")
            _require(material.get("base_outcome") == "pass" and material.get("head_outcome") == "fail"
                     and material.get("runner") == "pytest", "paired pytest candidate receipt required")
        indexed[case] = row
    for kind, archive in archives.items():
        row_key = "results" if kind == "click" else "bug_results"
        for i, archived_row in enumerate(archive[row_key]):
            prefix = f"/{row_key}/{i}/telemetry/"
            reviews = [indexed[m["case_id"]] for m in key["case_mapping"]
                       if m["source"] == INPUTS[kind].as_posix() and m["json_pointer"].startswith(prefix)]
            _require(sum(r["surfaced"] for r in reviews) == archived_row["reported"],
                     "candidate surfaced count mismatch")
    return indexed


def _cost(root, cost, population, archives, sources):
    _require(isinstance(cost, dict), "cost must be an object or null")
    _require(cost.get("currency") == "USD" and cost.get("complete") is True,
             "complete USD wallet and CI reconciliation required")
    for field in ("statement", "dispatch_inventory", "ci_receipt", "reconciliation_attestation"):
        _reference(root, cost.get(field))
    events, lines = cost.get("dispatches"), cost.get("statement_lines")
    _require(isinstance(events, list) and isinstance(lines, list), "dispatch/statement rows required")
    statement = strict_json((root / cost["statement"]["path"]).read_text())
    inventory = strict_json((root / cost["dispatch_inventory"]["path"]).read_text())
    ci_receipt = strict_json((root / cost["ci_receipt"]["path"]).read_text())
    attestation = strict_json((root / cost["reconciliation_attestation"]["path"]).read_text())
    _require(statement.get("currency") == "USD" and statement.get("lines") == lines,
             "statement rows/currency mismatch")
    _require(inventory.get("sources") == sources and inventory.get("dispatches") == events
             and inventory.get("complete") is True, "dispatch inventory mismatch")
    _require(attestation.get("sources") == sources and attestation.get("scope_complete") is True
             and isinstance(attestation.get("owner_id"), str) and attestation["owner_id"],
             "owner reconciliation attestation required")
    _require(ci_receipt.get("sources") == sources and ci_receipt.get("currency") == "USD"
             and ci_receipt.get("total_usd") == cost.get("ci_total_usd")
             and ci_receipt.get("allocation_usd") == cost.get("ci_allocation_usd"),
             "CI receipt/allocation mismatch")
    targets = {case: kind for (kind, _), case in population.items()}
    cohort_totals = {"bugs": Decimal(0), "click": Decimal(0)}
    event_ids, line_ids, charged = set(), set(), {}
    received = {}
    received_debits = {}
    total = Decimal(0)
    for e in events:
        _require(isinstance(e, dict), "invalid dispatch row")
        dispatch = e.get("dispatch_id")
        _require(isinstance(dispatch, str) and dispatch and dispatch not in event_ids, "duplicate/missing dispatch ID")
        event_ids.add(dispatch)
        target = e.get("target_case_id")
        _require(target in targets and e.get("stage") in ("generator", "assessor"), "dispatch scope mismatch")
        _require(e.get("transport_status") in ("response_received", "timeout", "transport_error"), "invalid transport status")
        _require(isinstance(e.get("provider_request_id"), str) and e["provider_request_id"], "unresolved provider request ID")
        amount = _amount(e.get("amount_usd"))
        _require(isinstance(e.get("statement_line_id"), str) and e["statement_line_id"], "unassigned dispatch debit")
        charged.setdefault(e["statement_line_id"], []).append((dispatch, amount))
        total += amount
        cohort_totals[targets[target]] += amount
        if e["transport_status"] == "response_received":
            received[target] = received.get(target, 0) + 1
            received_debits[target] = received_debits.get(target, Decimal(0)) + amount
    for line in lines:
        _require(isinstance(line, dict), "invalid statement line")
        identity = line.get("line_id")
        _require(isinstance(identity, str) and identity and identity not in line_ids, "duplicate/missing statement line")
        line_ids.add(identity)
        allocated = charged.get(identity, [])
        _require(isinstance(line.get("dispatch_ids"), list) and len(line["dispatch_ids"]) == len(allocated)
                 and set(line["dispatch_ids"]) == {d for d, _ in allocated}, "statement allocation mismatch")
        _require(_amount(line.get("amount_usd")) == sum((a for _, a in allocated), Decimal(0)),
                 "statement amount mismatch")
    _require(line_ids == set(charged), "unassigned statement line or dispatch")
    _require(total == _amount(cost.get("provider_total_usd")), "provider total mismatch")
    _require(_amount(statement.get("opening_balance")) + _amount(statement.get("topups"))
             + _amount(statement.get("refunds")) - _amount(statement.get("closing_balance"))
             - _amount(statement.get("other_debits")) == total, "wallet balance reconciliation mismatch")
    for kind, archive in archives.items():
        rows = archive["results" if kind == "click" else "bug_results"]
        for i, row in enumerate(rows):
            pointer = f"/results/{i}" if kind == "click" else f"/bug_results/{i}"
            if kind == "click":
                frame = archive["manifest"]["python_sampling_frame"]
                j = next(j for j, p in enumerate(frame) if p["pr_number"] == row["pr_number"])
                pointer = f"/manifest/python_sampling_frame/{j}"
            case = population[(kind, pointer)]
            _require(received.get(case, 0) == row["model_requests"], "received dispatch coverage mismatch")
            if row["model_requests"] > 0:
                observed_target = (_amount(row["provider_billing"]["provider_credit_debit_eur"])
                                   * _amount(archive["fx_usd_per_eur"]))
                _require(received_debits.get(case, Decimal(0)) >= observed_target,
                         "received target debit excludes archived credit/FX floor")
    observed = sum((Decimal(archive["fx_usd_per_eur"]) * sum((Decimal(
        r["provider_billing"]["provider_credit_debit_eur"]) for r in archive[
            "results" if kind == "click" else "bug_results"] if r["model_requests"] > 0), Decimal(0))
        for kind, archive in archives.items()), Decimal(0))
    _require(total >= observed, "provider total excludes observed response debits")
    ci = _amount(cost.get("ci_total_usd"))
    allocation = cost.get("ci_allocation_usd")
    _require(isinstance(allocation, dict) and set(allocation) == set(cohort_totals), "CI cohort allocation required")
    ci_by_cohort = {kind: _amount(value) for kind, value in allocation.items()}
    _require(sum(ci_by_cohort.values(), Decimal(0)) == ci, "CI allocations do not sum")
    return {"provider_total_usd": str(total), "ci_total_usd": str(ci), "all_in_total_usd": str(total + ci),
            "all_in_usd_per_attempted": {kind: {"total_usd": str(value + ci_by_cohort[kind]),
                "denominator": len(archives[kind]["results" if kind == "click" else "bug_results"]),
                "mean_usd": str((value + ci_by_cohort[kind]) / len(archives[kind][
                    "results" if kind == "click" else "bug_results"]))}
                for kind, value in cohort_totals.items()}}


def validate(manifest, root=ROOT):
    """Missing/invalid input is NO_GO; well-formed null evidence is blocked, not GA."""
    try:
        _require(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int
                 and manifest["schema_version"] == 1, "invalid acceptance schema")
        _require(set(manifest) == {"schema_version", "sources", "labels", "cost"}, "unexpected/missing acceptance fields")
        expected = blocked_checkpoint(root)["sources"]
        _require(manifest["sources"] == expected, "acceptance source/cohort binding mismatch")
        for ref in expected.values():
            _reference(root, ref)
        output = build(root)
        key = output["custodian-key.json"]
        archives = {kind: strict_json((root / path).read_text()) for kind, path in INPUTS.items()}
        indexed = _labels(root, manifest["labels"], output["reviewer-template.json"], key, archives, expected) if manifest["labels"] is not None else None
        population = {}
        for case in key["case_mapping"]:
            if case["json_pointer"].startswith("/manifest/python_sampling_frame/") or (
                case["source"] == INPUTS["bugs"].as_posix() and "/telemetry/" not in case["json_pointer"]):
                kind = "bugs" if case["source"] == INPUTS["bugs"].as_posix() else "click"
                population[(kind, case["json_pointer"])] = case["case_id"]
        totals = _cost(root, manifest["cost"], population, archives, expected) if manifest["cost"] is not None else None
        # No declaration of ga_ready is accepted. These are conditional cohort rates,
        # not representative universal recall or a multi-project clean-PR FPR.
        metrics = {"adjudicated_fpr": None, "adjudicated_defect_recall": None,
                   "provider_total_usd": None, "ci_total_usd": None, "all_in_total_usd": None}
        if indexed is not None:
            for kind, field in (("click", "adjudicated_fpr"), ("bugs", "adjudicated_defect_recall")):
                eligible = [(pointer, case) for (cohort, pointer), case in population.items() if cohort == kind
                            and indexed[case]["ground_truth"] == ("clean" if kind == "click" else "defect")]
                numerator = 0
                for pointer, _ in eligible:
                    if kind == "click":
                        p = archives[kind]["manifest"]["python_sampling_frame"][int(pointer.rsplit("/", 1)[1])]
                        row = next((r for r in archives[kind]["results"] if r["pr_number"] == p["pr_number"]), None)
                        numerator += bool(row and row["reported"] > 0)
                    else:
                        i = int(pointer.rsplit("/", 1)[1])
                        row = archives[kind]["bug_results"][i]
                        reported = [j for j, t in enumerate(row["telemetry"]) if t["disposition"] == "catching"]
                        for mapping in key["case_mapping"]:
                            if mapping["source"] == INPUTS[kind].as_posix() and mapping["json_pointer"] in {
                                f"/bug_results/{i}/telemetry/{j}" for j in reported}:
                                label = indexed[mapping["case_id"]]
                                if label["surfaced"] and label["assertion_valid"] and label["change_intent"] == "regression" and label["defect_correspondence"]:
                                    numerator += 1
                                    break
                _require(bool(eligible), "semantic denominator must be positive")
                metrics[field] = {"numerator": numerator, "denominator": len(eligible),
                                  "rate": str(Decimal(numerator) / len(eligible))}
        if totals:
            metrics.update(totals)
        blocked = [name for name in ("labels", "cost") if manifest[name] is None]
        return ValidatedAcceptance({"ok": True, "status": "blocked" if blocked else "accepted", "ga_ready": not blocked,
                "blockers": blocked, "source_sha256": {k: v["sha256"] for k, v in expected.items()},
                "metrics": metrics, "scope": "frozen_conditional_cohorts_only"})
    except (ValueError, TypeError, KeyError, OSError, ArithmeticError, StopIteration, AttributeError):
        return {"ok": False, "status": "invalid", "ga_ready": False,
                "problems": ["missing, malformed, unbound or incomplete GA73 evidence"]}


def load_acceptance(path=None, root=ROOT):
    try:
        manifest = blocked_checkpoint(root) if path is None else strict_json(Path(path).read_text())
        return validate(manifest, root)
    except (ValueError, TypeError, KeyError, OSError, ArithmeticError):
        return {"ok": False, "status": "invalid", "ga_ready": False,
                "problems": ["acceptance input unreadable or invalid JSON"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    result = load_acceptance(args.manifest)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
