"""Risk ranking: which changed symbols are worth spending money on.

Meta's paper reports that targeting matters as much as generation - they use a
Diff Risk Score to decide where to aim. We cannot use their model, so this is
an explicit, auditable heuristic. Every reason it fires is printed in the
report, so a maintainer can tell us it is wrong.

This is deliberately a heuristic and not a learned model. Once the ledger holds
a few thousand labelled outcomes, `human_outcome` becomes the training signal
and this file becomes the baseline we have to beat.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .diff import ChangeTarget

__all__ = ["RiskScore", "score_target", "rank", "WEIGHTS", "CONSEQUENTIAL", "BOUNDARY_OPS"]

# Domains where a silent wrong answer costs real money or real trust.
CONSEQUENTIAL = re.compile(
    r"\b(price|pricing|discount|charge|refund|invoice|payment|billing|tax|"
    r"balance|amount|currency|auth|authz|permission|token|session|password|"
    r"secret|crypt|hash|sign|verify|quota|limit|rate|retry|timeout|expire|"
    r"delete|drop|truncate|migrate|merge|reconcile|settle|ledger)\b",
    re.IGNORECASE,
)

# Off-by-one and empty-input territory.
BOUNDARY_OPS = re.compile(
    r"(\[[^\]]*:[^\]]*\]|\brange\(|\blen\(|\bmin\(|\bmax\(|\bround\(|\bint\(|"
    r"\bfloat\(|//|%|\+\s*1|-\s*1|\bsort|\breverse|\bindex\()"
)
_BRANCHY = re.compile(r"^\s*(if|elif|else|for|while|try|except|finally|match|case|with)\b",
                      re.MULTILINE)
_ERROR_PATHS = re.compile(r"\b(raise|except|assert|error|exception|fail)\b", re.IGNORECASE)
_CONCURRENCY = re.compile(r"\b(async|await|thread|lock|queue|process|concurrent|atomic)\b",
                          re.IGNORECASE)

WEIGHTS = {
    "branch_density": 0.22,
    "churn": 0.18,
    "boundary_ops": 0.18,
    "consequential_domain": 0.18,
    "modifies_existing": 0.14,
    "error_paths": 0.05,
    "concurrency": 0.05,
}


@dataclass
class RiskScore:
    target: ChangeTarget
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.score >= 0.70:
            return "high"
        if self.score >= 0.40:
            return "medium"
        return "low"


def _saturate(value: float, full: float) -> float:
    return min(1.0, value / full + 0.1) if full else 0.0


def score_target(target: ChangeTarget) -> RiskScore:
    after = target.source_after
    body_lines = max(1, len(after.splitlines()))
    haystack = f"{target.file_path} {target.symbol}\n{after}"

    signals = {
        "churn": _saturate(target.churn, 25),
        "branch_density": _saturate(len(_BRANCHY.findall(after)) / body_lines, 0.25),
        "boundary_ops": _saturate(len(BOUNDARY_OPS.findall(after)), 6),
        "consequential_domain": 1.0 if CONSEQUENTIAL.search(haystack) else 0.0,
        "modifies_existing": 1.0 if target.modifies_existing else 0.0,
        "error_paths": _saturate(len(_ERROR_PATHS.findall(after)), 4),
        "concurrency": 1.0 if _CONCURRENCY.search(after) else 0.0,
    }

    score = sum(WEIGHTS[k] * v for k, v in signals.items())

    # A two-line addition to a new helper is rarely worth a dollar of tokens.
    if target.churn <= 2 and not target.modifies_existing:
        score *= 0.5

    reasons = [k for k, v in sorted(signals.items(), key=lambda kv: -WEIGHTS[kv[0]] * kv[1])
               if v >= 0.5]
    return RiskScore(target=target, score=round(min(1.0, max(0.0, score)), 4),
                     reasons=reasons)


def rank(targets: list[ChangeTarget], threshold: float = 0.35,
         top_k: int = 5) -> list[RiskScore]:
    scored = [score_target(t) for t in targets]
    scored = [s for s in scored if s.score >= threshold]
    scored.sort(key=lambda s: (-s.score, s.target.qualified))
    return scored[:top_k]
