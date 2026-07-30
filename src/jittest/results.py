"""Run results: the report, its findings, and per-candidate telemetry.

These are the shapes the CLI renders, the eval harness parses, and the ledger
remembers. They live apart from the orchestration that produces them so the
contract can be reviewed without reading the pipeline.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from . import __version__
from .assess import Assessment
from .diff import ChangeTarget
from .execute import Disposition

__all__ = ["CandidateTelemetry", "Finding", "Report", "DISPOSITIONS"]


# Disposition values for per-candidate telemetry.
#
# The oracle owns every value it can produce (execute.Disposition). The three
# below describe endings reached before the oracle ever ran, so they live here.
# Defect 38: this tuple is the whole vocabulary, and none of it is recovered by
# searching English prose any more.
_PRE_ORACLE_DISPOSITIONS = (
    "model_declined",          # model returned NO_CANDIDATE or empty
    "parse_failed",            # response could not be parsed as code
    "safety_rejected",         # static safety gate rejected the candidate
)

DISPOSITIONS = _PRE_ORACLE_DISPOSITIONS + tuple(d.value for d in Disposition)


@dataclass
class CandidateTelemetry:
    """Structured per-candidate telemetry line.

    Never contains candidate source code or API keys.
    """
    target_symbol: str = ""
    target_file: str = ""
    risk_score: float = 0.0
    candidate_index: int = 0
    disposition: str = ""
    head_outcome: str = ""
    base_outcome: str = ""
    rerun_agreement: bool = True
    assessor_verdict: str = ""
    assessor_confidence: float = 0.0
    failure_excerpt: str = ""

    def as_dict(self) -> dict:
        return {
            "target_symbol": self.target_symbol,
            "target_file": self.target_file,
            "risk_score": self.risk_score,
            "candidate_index": self.candidate_index,
            "disposition": self.disposition,
            "head_outcome": self.head_outcome,
            "base_outcome": self.base_outcome,
            "rerun_agreement": self.rerun_agreement,
            "assessor_verdict": self.assessor_verdict,
            "assessor_confidence": self.assessor_confidence,
            "failure_excerpt": self.failure_excerpt,
        }

    def as_jsonl(self) -> str:
        return json.dumps(self.as_dict())


@dataclass
class Finding:
    target: ChangeTarget
    test_code: str
    oracle_reason: str
    failure_excerpt: str
    assessment: Assessment
    risk_score: float
    risk_reasons: list[str]
    repro_command: str
    ledger_id: int | None = None
    latent: bool = False


@dataclass
class Report:
    repo: str
    base: str
    head: str
    model: str
    findings: list[Finding] = field(default_factory=list)
    latent_findings: list[Finding] = field(default_factory=list)
    targets_considered: int = 0
    targets_skipped: int = 0
    candidates_generated: int = 0
    discarded: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    priced: bool = True
    # Whether any token count behind cost_usd was estimated rather than
    # reported by the provider. Kept separate from `priced` because the two
    # failure modes are different: no price at all, versus a real price
    # applied to approximate tokens.
    tokens_estimated: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    reruns: int = 2
    errors: list[str] = field(default_factory=list)
    version: str = __version__
    telemetry: list[CandidateTelemetry] = field(default_factory=list)
    # Number of model requests actually issued during this run. This is the
    # only honest answer to "was anything measured?". Elapsed time is not.
    model_requests: int = 0
    # How the diff step ended. "ok" means git ran and produced changed code.
    # "empty" is a fact about the revision pair. "git_failed" is the absence of
    # a fact: nothing was examined. A consumer that averages "empty" and
    # "git_failed" together as "no findings" is computing a false catch rate.
    diff_status: str = "ok"
    # How candidates were confined. Recorded rather than assumed, because a
    # user who believes model-written code ran in a container when it ran on
    # the bare runner has been misled about the only thing that makes it safe
    # to point this tool at a stranger's pull request.
    sandbox: dict = field(default_factory=lambda: {
        "backend": "none", "image": None, "isolated": False,
        "network_denied": False, "notes": [],
    })

    @property
    def has_regression(self) -> bool:
        return any(f.assessment.should_report for f in self.findings)

    @property
    def cost_line(self) -> str:
        if not self.priced:
            tokens = self.input_tokens + self.output_tokens
            if tokens:
                # No dollar figure, but the run is no longer unmeasured: the
                # token count is the thing an operator can price themselves.
                return f"unpriced ({tokens:,} tokens)"
            return "unpriced"
        if self.tokens_estimated:
            return f"~${self.cost_usd:.3f} (estimated tokens)"
        return f"${self.cost_usd:.3f}"

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "repo": self.repo,
            "base": self.base,
            "head": self.head,
            "model": self.model,
            "targets_considered": self.targets_considered,
            "targets_skipped": self.targets_skipped,
            "candidates_generated": self.candidates_generated,
            "discarded": self.discarded,
            "cost_usd": round(self.cost_usd, 4),
            "priced": self.priced,
            "tokens_estimated": self.tokens_estimated,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_s": round(self.duration_s, 2),
            "model_requests": self.model_requests,
            "diff_status": self.diff_status,
            "sandbox": self.sandbox,
            "has_regression": self.has_regression,
            "errors": self.errors,
            "telemetry": [t.as_dict() for t in self.telemetry],
            "findings": [
                {
                    "file": f.target.file_path,
                    "symbol": f.target.symbol,
                    "risk_score": f.risk_score,
                    "risk_reasons": f.risk_reasons,
                    "oracle_reason": f.oracle_reason,
                    "assessment": f.assessment.as_dict(),
                    "test_code": f.test_code,
                    "repro_command": f.repro_command,
                }
                for f in self.findings
            ],
            "latent": [
                {"file": f.target.file_path, "symbol": f.target.symbol}
                for f in self.latent_findings
            ],
        }
