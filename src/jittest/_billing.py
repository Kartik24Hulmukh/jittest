"""Shared conservative classification of terminal billing refusals."""
from __future__ import annotations


def billing_refusal(status: int, detail: str) -> bool:
    if status == 402:
        return True
    if status != 429:
        return False
    detail = detail.lower()
    return any(marker in detail for marker in (
        "insufficient_quota", "billing_error", "insufficient credits",
        "insufficient balance", "quota_exceeded", "credit balance",
    ))


class BillingTotals:
    """Aggregate documented provider EUR equivalents using decimal arithmetic.

    Missing/invalid billing withholds totals. Energy is not falsely called a
    credit debit. This is provider response evidence, not a wallet statement.
    """

    def __init__(self) -> None:
        from decimal import Decimal
        self.equivalent_eur = Decimal(0)
        self.credit_debit_eur = Decimal(0)
        self.responses = 0
        self.complete = True
        self.paid_with: set[str] = set()

    def add(self, billing: object) -> None:
        from decimal import Decimal, InvalidOperation
        self.responses += 1
        if not isinstance(billing, dict) or billing.get("paid_with") not in ("energy", "credits"):
            self.complete = False
            return
        try:
            raw = billing.get("credits")
            if not isinstance(raw, str) or len(raw) > 128:
                raise ValueError("credits must be a decimal string")
            eur = Decimal(raw)
            exponent = eur.as_tuple().exponent
            if (not eur.is_finite() or eur < 0 or not isinstance(exponent, int)
                    or not -128 <= exponent <= 128):
                raise ValueError("credits must be finite and nonnegative")
        except (InvalidOperation, ValueError):
            self.complete = False
            return
        self.equivalent_eur += eur
        if billing["paid_with"] == "credits":
            self.credit_debit_eur += eur
        self.paid_with.add(billing["paid_with"])

    def as_dict(self) -> dict:
        valid = self.responses > 0 and self.complete
        return {"provider_cost_eur": str(self.equivalent_eur) if valid else None,
                "provider_credit_debit_eur": str(self.credit_debit_eur) if valid else None,
                "provider_billing_complete": valid, "provider_response_count": self.responses,
                "provider_paid_with": sorted(self.paid_with)}


def _ledger_decimal(value: object):
    from decimal import Decimal, InvalidOperation

    if not isinstance(value, str) or len(value) > 128:
        raise ValueError("documented equivalent must be a decimal string")
    try:
        amount = Decimal(value)
        exponent = amount.as_tuple().exponent
        if (not amount.is_finite() or amount < 0 or not isinstance(exponent, int)
                or not -128 <= exponent <= 128):
            raise ValueError("invalid documented equivalent")
    except InvalidOperation as exc:
        raise ValueError("invalid documented equivalent") from exc
    return amount


def _validate_ledger_event(event: object) -> dict:
    """Refuse malformed observations; genuinely absent attribution stays unknown."""
    import re
    from datetime import datetime, timedelta

    if not isinstance(event, dict):
        raise ValueError("dispatch ledger event must be an object")
    version = event.get("schema_version")
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ValueError("unsupported dispatch ledger schema")
    for field in ("run_id", "target_id", "provider_request_id", "invocation_id"):
        value = event.get(field)
        if value is not None and (not isinstance(value, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value)):
            raise ValueError("invalid ledger attribution identifier")
    if event.get("stage") not in (None, "generator", "assessor"):
        raise ValueError("invalid ledger stage")
    body = event.get("body_parse_status")
    content = event.get("content_parse_status")
    usage = event.get("usage_parse_status")
    statuses = ("not_attempted", "parsed", "failed")
    if any(value not in statuses for value in (body, content, usage)):
        raise ValueError("invalid ledger parse status")
    received = event.get("received_body")
    if not isinstance(received, bool):
        raise ValueError("received_body must be boolean")
    equivalent = event.get("provider_equivalent_eur")
    state = event.get("debit_observation_status")
    kind = event.get("event_type")
    if kind not in ("dispatch", "cache_hit", "budget_refusal", "pre_dispatch_error"):
        raise ValueError("unknown dispatch ledger event type")
    if kind != "dispatch":
        if (event.get("dispatch_timestamp_utc") is not None or event.get("retry_index") is not None
                or event.get("transport_status") != "not_dispatched" or received
                or event.get("http_status") is not None or event.get("provider_request_id") is not None
                or equivalent is not None or state != "unknown"
                or content != "not_attempted" or usage != "not_attempted"
                or (kind != "cache_hit" and body != "not_attempted")):
            raise ValueError("nondispatch event cannot claim transport observations")
        return event
    identity = event.get("dispatch_id")
    if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", identity):
        raise ValueError("invalid dispatch id")
    stamp = event.get("dispatch_timestamp_utc")
    if not isinstance(stamp, str) or len(stamp) > 64:
        raise ValueError("dispatch requires an aware UTC timestamp")
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError as exc:
        raise ValueError("invalid dispatch timestamp") from exc
    if when.tzinfo is None or when.utcoffset() != timedelta(0):
        raise ValueError("dispatch timestamp must be aware UTC")
    transport = event.get("transport_status")
    if transport not in ("started", "response_received", "http_error", "timeout", "transport_error"):
        raise ValueError("invalid transport status")
    status = event.get("http_status")
    if status is not None and (isinstance(status, bool) or not isinstance(status, int)
                              or not 100 <= status <= 599):
        raise ValueError("invalid HTTP status")
    if (transport == "response_received" and (status is None or status >= 400)
            or transport == "http_error" and (status is None or status < 400)
            or transport == "started" and status is not None):
        raise ValueError("HTTP status conflicts with transport observation")
    if received and transport not in ("response_received", "http_error"):
        raise ValueError("received body conflicts with transport observation")
    if not received and any(value != "not_attempted" for value in (body, content, usage)):
        raise ValueError("parse observations require a received body")
    if ((content != "not_attempted" and body != "parsed")
            or (usage != "not_attempted" and content != "parsed")):
        raise ValueError("parse status conflicts with preceding phase")
    if state in ("observed", "noncredit"):
        if not received or body != "parsed" or transport not in ("response_received", "http_error"):
            raise ValueError("billing observation requires a received parsed body")
        amount = _ledger_decimal(equivalent)
        if state == "observed" and _ledger_decimal(event.get("credit_debit_eur")) != amount:
            raise ValueError("credit debit conflicts with documented equivalent")
    elif equivalent is not None:
        raise ValueError("unknown debit cannot claim a documented equivalent")
    return event


def summarize_dispatch_ledger(events: list[dict]) -> dict:
    """Validate opt-in dispatch evidence and summarize observed subsets only.

    No statement joins, exchange rates or CI allocation are invented. A fully
    observed transport ledger is still not independently reconciled expense.
    """
    from collections import Counter
    from decimal import Decimal, InvalidOperation

    if not isinstance(events, list):
        raise ValueError("dispatch ledger must be an event list")
    kinds = {"dispatch", "cache_hit", "budget_refusal", "pre_dispatch_error"}
    transports = {"started", "response_received", "http_error", "timeout", "transport_error"}
    dispatch_ids: set[str] = set()
    invocation_ids: set[str] = set()
    observed = Decimal(0)
    observed_count = unknown_count = noncredit_count = missing_request_ids = 0
    missing_invocations = missing_context = 0
    for raw_event in events:
        event = _validate_ledger_event(raw_event)
        kind = event.get("event_type")
        if kind not in kinds:
            raise ValueError("unknown dispatch ledger event type")
        invocation = event.get("invocation_id")
        if invocation is None:
            missing_invocations += 1
        elif not isinstance(invocation, str) or not invocation:
            raise ValueError("invalid invocation id")
        else:
            invocation_ids.add(invocation)
        if kind != "dispatch":
            if event.get("dispatch_id") is not None or event.get("credit_debit_eur") is not None:
                raise ValueError("nondispatch event cannot claim a dispatch or debit")
            continue
        identity = event.get("dispatch_id")
        if not isinstance(identity, str) or not identity or identity in dispatch_ids:
            raise ValueError("missing or duplicate dispatch id")
        dispatch_ids.add(identity)
        retry = event.get("retry_index")
        if isinstance(retry, bool) or not isinstance(retry, int) or retry < 0:
            raise ValueError("invalid retry index")
        if event.get("transport_status") not in transports:
            raise ValueError("invalid transport status")
        if event.get("provider_request_id") is None:
            missing_request_ids += 1
        if any(event.get(key) is None for key in ("run_id", "target_id", "stage")):
            missing_context += 1
        state = event.get("debit_observation_status")
        amount = event.get("credit_debit_eur")
        if state == "observed":
            if (event.get("received_body") is not True or not isinstance(amount, str)
                    or len(amount) > 128 or event.get("transport_status") not in ("response_received", "http_error")):
                raise ValueError("observed debit requires received body and decimal string")
            try:
                value = Decimal(amount)
                exponent = value.as_tuple().exponent
                if (not value.is_finite() or value < 0 or not isinstance(exponent, int)
                        or not -128 <= exponent <= 128):
                    raise ValueError("invalid observed debit")
            except InvalidOperation as exc:
                raise ValueError("invalid observed debit") from exc
            observed += value
            observed_count += 1
        elif state in ("unknown", "noncredit"):
            if amount is not None:
                raise ValueError("unobserved credit debit must remain null")
            if state == "unknown":
                unknown_count += 1
            else:
                noncredit_count += 1
        else:
            raise ValueError("invalid debit observation status")
    dispatched = [e for e in events if e["event_type"] == "dispatch"]
    return {
        "scope": "instrumented_client_observed_dispatch_subset_not_wallet_reconciliation",
        "event_counts": dict(sorted(Counter(e["event_type"] for e in events).items())),
        "actual_dispatches": len(dispatched),
        "retry_dispatches": sum(e["retry_index"] > 0 for e in dispatched),
        "known_invocations": len(invocation_ids),
        "events_missing_invocation": missing_invocations,
        "transport_counts": dict(sorted(Counter(e["transport_status"] for e in dispatched).items())),
        "unterminated_dispatches": sum(e["transport_status"] == "started" for e in dispatched),
        "body_parse_failures": sum(e.get("body_parse_status") == "failed" for e in events),
        "content_parse_failures": sum(e.get("content_parse_status") == "failed" for e in events),
        "usage_parse_failures": sum(e.get("usage_parse_status") == "failed" for e in events),
        "observed_credit_dispatches": observed_count,
        "observed_credit_debit_eur": str(observed) if observed_count else None,
        "unknown_debit_dispatches": unknown_count,
        "noncredit_dispatches": noncredit_count,
        "dispatches_missing_provider_request_id": missing_request_ids,
        "dispatches_missing_run_target_or_stage": missing_context,
        "wallet_invoice_reconciled": False,
        "total_reconciled_provider_usd": None,
        "ci_runtime_expense_usd": None,
    }
