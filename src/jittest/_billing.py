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


def summarize_dispatch_ledger(events: list[dict]) -> dict:
    """Validate opt-in dispatch evidence and summarize observed subsets only.

    No statement joins, exchange rates or CI allocation are invented. A fully
    observed transport ledger is still not independently reconciled expense.
    """
    from collections import Counter
    from decimal import Decimal, InvalidOperation

    kinds = {"dispatch", "cache_hit", "budget_refusal", "pre_dispatch_error"}
    transports = {"started", "response_received", "http_error", "timeout", "transport_error"}
    dispatch_ids: set[str] = set()
    invocation_ids: set[str] = set()
    observed = Decimal(0)
    observed_count = unknown_count = noncredit_count = missing_request_ids = 0
    missing_invocations = missing_context = 0
    for event in events:
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
