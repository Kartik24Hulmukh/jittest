"""The assessor layer.

Meta reports that assessor agents cut reviewer load by roughly 70% (arXiv
2601.22832). That number is the difference between a tool people keep switched
on and one they mute in week two: independent 2026 measurements put 15-30% of
AI review comments in the low-value or incorrect bucket.

The oracle decides whether a test is *true*. The assessor decides whether it is
*worth saying*. Only a confident real_regression is reported by default.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Assessment", "parse_assessment", "MIN_CONFIDENCE", "VALID_VERDICTS"]

MIN_CONFIDENCE = 0.70
VALID_VERDICTS = ("real_regression", "intended_change", "unclear")
VALID_SEVERITY = ("low", "medium", "high")


def _coerce_confidence(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if value > 1.0:                 # models like answering "85"
        value = value / 100.0
    return min(1.0, max(0.0, value))


@dataclass
class Assessment:
    verdict: str = "unclear"
    confidence: float = 0.0
    severity: str = "medium"
    summary: str = ""
    reviewer_question: str = ""
    raw: str = ""

    @property
    def should_report(self) -> bool:
        return self.verdict == "real_regression" and self.confidence >= MIN_CONFIDENCE

    @property
    def badge(self) -> str:
        return {
            "real_regression": "likely regression",
            "intended_change": "looks intended",
            "unclear": "needs a human",
        }.get(self.verdict, "needs a human")

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "confidence": self.confidence,
            "severity": self.severity,
            "summary": self.summary,
            "reviewer_question": self.reviewer_question,
            "should_report": self.should_report,
        }


def parse_assessment(payload: dict | None, raw: str = "") -> Assessment:
    """Never raise. A malformed assessor reply degrades to `unclear`, which is
    not reported - failing closed is the whole point of this layer."""
    if not isinstance(payload, dict):
        return Assessment(summary="assessor returned unparseable output", raw=raw)

    verdict = str(payload.get("verdict", "")).strip().lower()
    if verdict not in VALID_VERDICTS:
        verdict = "unclear"

    severity = str(payload.get("severity", "medium")).strip().lower()
    if severity not in VALID_SEVERITY:
        severity = "medium"

    confidence = _coerce_confidence(payload.get("confidence", 0.0))
    if verdict == "unclear":
        confidence = min(confidence, MIN_CONFIDENCE - 0.01)

    return Assessment(
        verdict=verdict,
        confidence=confidence,
        severity=severity,
        summary=str(payload.get("summary", "")).strip()[:300],
        reviewer_question=str(payload.get("reviewer_question", "")).strip()[:300],
        raw=raw,
    )
