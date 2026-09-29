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
