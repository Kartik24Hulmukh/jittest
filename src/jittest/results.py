"""Run results: the report, its findings, and per-candidate telemetry.

These are the shapes the CLI renders, the eval harness parses, and the ledger
remembers. They live apart from the orchestration that produces them so the
contract can be reviewed without reading the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    "rate_limited",            # model request was rate limited after retries
    "timed_out",               # model request timed out on all retries
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
    # Why the static safety gate rejected this candidate. Populated only for
    # disposition == "safety_rejected". This string is written by
    # safety.check_candidate, which is our code describing a rule that fired;
    # it is not model output, so it is recorded verbatim.
    check_reason: str = ""
    # Structural digest of a response that would not parse. Populated only for
    # disposition == "parse_failed". NOT the raw text: see
    # _pipeline_helpers.parse_failure_digest for why, and for exactly which
    # fields are and are not included.
    parse_error: str = ""
    # SHA-256 hex digest and relative path to run-scoped local candidate source file.
    # The actual candidate source text is stored in local disk (.jittest/candidates/<run_id>/)
    # and NEVER exported to telemetry.
    candidate_source_sha256: str = ""
    candidate_source_path: str = ""
    # Phase-2 observability (task 27). Additive only. refusal_code is the
    # machine-readable refusal taxonomy code (docs/ERRORS.md) or "";
    # sandbox_backend / sandbox_image_digest restate the confinement actually
    # used so a telemetry line can never imply isolation that did not happen;
    # wall_clock_s is the oracle wall clock for this candidate. None of these
    # ever carries candidate source text (docs/PRIVACY.md).
    refusal_code: str = ""
    sandbox_backend: str = ""
    sandbox_image_digest: str = ""
    wall_clock_s: float = 0.0

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
            "check_reason": self.check_reason,
            "parse_error": self.parse_error,
            "candidate_source_sha256": self.candidate_source_sha256,
            "candidate_source_path": self.candidate_source_path,
            "refusal_code": self.refusal_code,
            "sandbox_backend": self.sandbox_backend,
            "sandbox_image_digest": self.sandbox_image_digest,
            "wall_clock_s": round(float(self.wall_clock_s), 3),
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
    provider_billing: dict | None = None
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
    model_request_attempts: int = 0
    rate_limited_candidates: int = 0
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
    # Phase-2 observability (task 27): total wall clock and per-phase timings
    # in seconds. Local only; nothing here is transmitted anywhere.
    wall_clock_s: float = 0.0
    phases: dict = field(default_factory=lambda: {"run_total_s": 0.0, "oracle_s": 0.0})

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
            "provider_billing": self.provider_billing,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_s": round(self.duration_s, 2),
            "model_requests": self.model_requests,
            "model_request_attempts": self.model_request_attempts,
            "rate_limited_candidates": self.rate_limited_candidates,
            "diff_status": self.diff_status,
            "sandbox": self.sandbox,
            "wall_clock_s": round(float(self.wall_clock_s), 3),
            "phases": {k: round(float(v), 3) for k, v in self.phases.items()},
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


class AttemptCensus:
    """Observed invocation ledger, not a semantic evaluation or ground truth.

    Journal records are fsynced before an atomic snapshot is published. Each
    invocation owns a unique directory, so concurrent invocations cannot merge
    denominators. Pending entries after abrupt termination remain pending.
    """

    def __init__(self, directory: Path | None, *, entrypoint: str):
        self.directory = directory
        self.data: dict[str, Any] = {
            "schema_version": "default-attempt-census-1.0", "run_id": uuid.uuid4().hex,
            "entrypoint": entrypoint, "denominator_known": False,
            "candidates": [], "state": "started", "journal_records": 0,
            "journal_sha256": hashlib.sha256(b"").hexdigest(),
        }
        self.phases: list[dict[str, Any]] = []
        self._journal = hashlib.sha256()
        if directory is not None:
            self.directory = directory / self.data["run_id"]
            self.directory.mkdir(parents=True, exist_ok=False)
        self.event("invocation_started")

    @staticmethod
    def candidate(*, selector: str, base: str | None, head: str | None,
                  source: bytes | None, base_ref: str | None = None,
                  head_ref: str | None = None) -> dict[str, Any]:
        material = {"selector": selector, "base_sha": base, "head_sha": head,
                    "base_ref": base_ref, "head_ref": head_ref,
                    "candidate_sha256": hashlib.sha256(source).hexdigest() if source is not None else None,
                    "candidate_bytes": len(source) if source is not None else None}
        digest = hashlib.sha256(json.dumps(material, sort_keys=True,
                                separators=(",", ":")).encode()).hexdigest()
        return {**material, "material_sha256": digest, "state": "pending",
                "disposition": None, "execution_observed": False}

    def select(self, candidates: list[dict[str, Any]], *, known: bool = True) -> None:
        self.data["candidates"] = candidates
        self.data["denominator_known"] = known
        self.event("candidates_selected", candidates=candidates, denominator_known=known)

    def event(self, event: str, **fields: Any) -> None:
        record = {"sequence": self.data["journal_records"] + 1,
                  "run_id": self.data["run_id"], "event": event, **fields}
        line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if self.directory is not None:
            with (self.directory / "journal.jsonl").open("ab") as stream:
                stream.write(line)
                stream.flush()
                os.fsync(stream.fileno())
        self._journal.update(line)
        self.data["journal_records"] = record["sequence"]
        self.data["journal_sha256"] = self._journal.hexdigest()
        self._snapshot()

    def bind_candidate(self, index: int, *, base: str, head: str, source: bytes) -> None:
        candidate = self.data["candidates"][index]
        material = self.candidate(selector=candidate["selector"], base=base, head=head,
                                  source=source, base_ref=candidate["base_ref"],
                                  head_ref=candidate["head_ref"])
        candidate.update({k: v for k, v in material.items()
                          if k not in ("state", "disposition", "execution_observed")})
        self.event("candidate_material_bound", candidate_index=index, material=material)

    def start_candidate(self, index: int) -> None:
        self.data["candidates"][index]["state"] = "attempted"
        self.event("candidate_started", candidate_index=index)

    def finish_candidate(self, index: int, *, disposition: str,
                         phases: list[dict[str, Any]] | None = None,
                         artifact: str | None = None, error_type: str | None = None) -> None:
        candidate = self.data["candidates"][index]
        candidate.update(state="finished", disposition=disposition,
                         execution_observed=any("outcome" in p for p in (phases or [])))
        if artifact is not None:
            candidate["artifact"] = artifact
        self.event("candidate_finished", candidate_index=index, disposition=disposition,
                   phases=phases or [], artifact=artifact, error_type=error_type)

    def finish(self, state: str = "finished") -> dict[str, Any]:
        self.data["state"] = state
        self.event("invocation_finished", state=state)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data))

    def _snapshot(self) -> None:
        if self.directory is not None:
            temporary = self.directory / "snapshot.tmp"
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(self.data, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / "snapshot.json")
