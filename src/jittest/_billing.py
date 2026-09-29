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
