#!/usr/bin/env python3
"""Reconcile local provider-billing evidence against an owner-exported wallet statement.

Issue #73 requires "provider wallet/invoice reconciliation including
failed/unreceived calls and all-in CI costs". The Melious API exposes no
billing, balance, usage, or invoice endpoint (nine candidate routes probed
2026-10-04, all HTTP 404; see docs/WALLET-RECONCILIATION.md), so the wallet
side must come from an owner dashboard export. This script is the turnkey
half: it validates that export, sums every received-response debit retained
in local evidence artifacts with exact Decimal arithmetic, counts
failed/unreceived calls whose spend is unobservable, and reports the implied
unaccounted spend instead of assuming it is zero.

Fail-closed contract:
  exit 0 - wallet spend is consistent with local evidence (delta covers debits)
  exit 1 - inconsistency: debits exceed wallet spend or invoice disagrees
  exit 2 - malformed input (artifact, wallet export, or CLI misuse)

This tool never fabricates missing wallet data. --print-template emits the
exact JSON shape the owner must fill from the provider dashboard.

Run: python3 scripts/reconcile_wallet.py --wallet wallet.json \
       --artifact docs/evidence/live-routing-20261004/live-routing-100x-run1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

WALLET_SCHEMA = "jittest/wallet-export/1"
REPORT_SCHEMA = "jittest/wallet-reconciliation/1"

WALLET_TEMPLATE = {
    "schema": WALLET_SCHEMA,
    "source": "melious-dashboard",
    "currency": "EUR",
    "period_start": "YYYY-MM-DDTHH:MM:SSZ",
    "period_end": "YYYY-MM-DDTHH:MM:SSZ",
    "opening_balance": "0.00000000",
    "closing_balance": "0.00000000",
    "topups_total": "0.00000000",
    "invoiced_total": None,
    "notes": "Export taken from the provider web dashboard; the Melious API "
             "exposes no billing endpoint (verified 2026-10-04, 9 routes, all 404).",
}

_AMOUNT_FIELDS = ("opening_balance", "closing_balance", "topups_total")


class InputError(Exception):
    """Malformed artifact or wallet export (exit 2)."""


def _parse_amount(value: object, field: str) -> Decimal:
    """Parse a nonnegative finite decimal string; reject bools/floats/exotica."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise InputError(f"{field} must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise InputError(f"{field} is not a decimal: {value!r}") from exc
    exponent = amount.as_tuple().exponent
    if (not amount.is_finite() or amount < 0 or not isinstance(exponent, int)
            or not -128 <= exponent <= 128):
        raise InputError(f"{field} must be finite and nonnegative")
    return amount


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InputError("nonfinite JSON constant")


def _decode_json(raw: str) -> object:
    return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _validate_wallet(data: dict) -> None:
    if data.get("schema") != WALLET_SCHEMA:
        raise InputError(f"wallet schema must be {WALLET_SCHEMA!r}")
    for field in ("source", "currency", "period_start", "period_end"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise InputError(f"wallet field {field!r} must be a nonempty string")
    # Retained provider_credit_debit_eur values cannot be relabeled as USD.
    if data["currency"] != "EUR":
        raise InputError("wallet currency must be EUR; USD conversion belongs in GA acceptance")
    times = []
    for field in ("period_start", "period_end"):
        try:
            stamp = datetime.fromisoformat(data[field].replace("Z", "+00:00"))
        except ValueError as exc:
            raise InputError(f"wallet {field} must be an ISO-8601 timestamp") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise InputError(f"wallet {field} must include a timezone")
        times.append(stamp)
    if times[0] >= times[1]:
        raise InputError("wallet period_start must precede period_end")
    for field in _AMOUNT_FIELDS:
        _parse_amount(data.get(field), field)
    if data.get("invoiced_total") is not None:
        _parse_amount(data["invoiced_total"], "invoiced_total")


def load_wallet(path: Path) -> dict:
    try:
        data = _decode_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"wallet export unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("wallet export must be a JSON object")
    _validate_wallet(data)
    return data


def _row_billing_debit(row: dict) -> Decimal | None:
    billing = row.get("provider_billing")
    if not isinstance(billing, dict):
        return None
    raw = billing.get("provider_credit_debit_eur")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise InputError("provider_billing.provider_credit_debit_eur must be a string or null")
    return _parse_amount(raw, "provider_billing.provider_credit_debit_eur")


def load_artifact(path: Path) -> dict:
    try:
        raw = path.read_bytes()
        data = _decode_json(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InputError(f"artifact unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise InputError(f"artifact must be an evidence object with a rows list: {path}")
    received = Decimal(0)
    calls = failed = unbilled_ok = 0
    for row in data["rows"]:
        if not isinstance(row, dict):
            raise InputError("artifact rows must be JSON objects")
        if row.get("case") != "completion":
            continue
        if row.get("status") not in ("ok", "failed", "error"):
            raise InputError("completion row has an unknown status")
        calls += 1
        if row.get("status") != "ok":
            failed += 1
            continue
        debit = _row_billing_debit(row)
        if debit is None:
            unbilled_ok += 1
        else:
            with localcontext() as ctx:
                ctx.prec = 512
                received += debit
    if calls == 0:
        raise InputError("artifact contains no completion calls")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "evidence_sha": data.get("sha"),
        "completion_calls": calls,
        "failed_or_unreceived_calls": failed,
        "ok_calls_without_billing_row": unbilled_ok,
        "received_credit_debits": received,
    }


def _reconcile_exact(wallet: dict, artifacts: list[dict]) -> dict:
    _validate_wallet(wallet)
    if not artifacts:
        raise InputError("at least one artifact is required")
    hashes = [a["sha256"] for a in artifacts]
    if len(set(hashes)) != len(hashes):
        raise InputError("duplicate artifact content; each run may be counted only once")
    opening = _parse_amount(wallet["opening_balance"], "opening_balance")
    closing = _parse_amount(wallet["closing_balance"], "closing_balance")
    topups = _parse_amount(wallet["topups_total"], "topups_total")
    invoiced_raw = wallet.get("invoiced_total")
    invoiced = None if invoiced_raw is None else _parse_amount(invoiced_raw, "invoiced_total")

    wallet_spend = opening + topups - closing
    received = sum((a["received_credit_debits"] for a in artifacts), Decimal(0))
    failed = sum(a["failed_or_unreceived_calls"] for a in artifacts)
    unbilled_ok = sum(a["ok_calls_without_billing_row"] for a in artifacts)
    calls = sum(a["completion_calls"] for a in artifacts)
    implied_unaccounted = wallet_spend - received
    consistent = implied_unaccounted >= 0

    invoice_matches = None
    if invoiced is not None:
        invoice_matches = invoiced == wallet_spend
        consistent = consistent and invoice_matches

    return {
        "schema": REPORT_SCHEMA,
        "currency": wallet["currency"],
        "period": {"start": wallet["period_start"], "end": wallet["period_end"]},
        "wallet_source": wallet["source"],
        "artifacts": [{k: (str(v) if isinstance(v, Decimal) else v)
                       for k, v in a.items()} for a in artifacts],
        "completion_calls": calls,
        "failed_or_unreceived_calls": failed,
        "ok_calls_without_billing_row": unbilled_ok,
        "received_credit_debits": str(received),
        "wallet_observed_spend": str(wallet_spend),
        "implied_unaccounted_spend": str(implied_unaccounted),
        "invoiced_total": None if invoiced is None else str(invoiced),
        "invoice_matches_wallet_delta": invoice_matches,
        "consistent": consistent,
        "non_claims": [
            "Implied unaccounted spend is an upper bound covering failed or "
            "unreceived calls, non-artifact usage in the period, and rounding; "
            "it is not attributed to any single cause.",
            "This report reconciles provider debits only. CI compute minutes "
            "and other launch costs are outside the provider wallet.",
            "Consistency of totals is not proof the wallet export is authentic; "
            "source custody of the dashboard export remains with the owner.",
        ],
    }


def reconcile(wallet: dict, artifacts: list[dict]) -> dict:
    # Inputs allow 128 digits and exponents +/-128. Default Decimal precision
    # (28) silently rounds subtraction/sums; 512 preserves the supported range.
    with localcontext() as ctx:
        ctx.prec = 512
        return _reconcile_exact(wallet, artifacts)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wallet", type=Path, help="owner-exported wallet statement JSON")
    ap.add_argument("--artifact", type=Path, action="append", default=[],
                    help="live-evidence artifact JSON (repeatable)")
    ap.add_argument("--out", type=Path, help="write report JSON here (default stdout)")
    ap.add_argument("--print-template", action="store_true",
                    help="print the wallet-export template the owner must fill and exit")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_template:
        print(json.dumps(WALLET_TEMPLATE, indent=2))
        return 0
    if args.wallet is None or not args.artifact:
        print("error: --wallet and at least one --artifact are required "
              "(or use --print-template)", file=sys.stderr)
        return 2
    try:
        wallet = load_wallet(args.wallet)
        artifacts = [load_artifact(p) for p in args.artifact]
        report = reconcile(wallet, artifacts)
    except InputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2) + "\n"
    if args.out is not None:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    if not report["consistent"]:
        print("error: provider debits or invoice disagree with wallet-observed spend; "
              "evidence and wallet statement disagree", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
