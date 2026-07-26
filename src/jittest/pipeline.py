"""Orchestration: diff in, proven catching tests out.

    git diff
      -> change targets (functions, not files)
      -> risk ranking (the cost gate)
      -> N candidate tests per target (the only step a model decides)
      -> static safety gate
      -> DIFFERENTIAL ORACLE   <- load-bearing, no model involved
      -> assessor (regression, or intended change?)
      -> ledger + report

The base and head worktrees are created once per run and reused for every
candidate. That single decision is what makes three executions per candidate
affordable, and three executions per candidate is what buys the flakiness
rerun that keeps the report trustworthy.
"""
from __future__ import annotations

import time
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__
from . import prompts as P
from .assess import Assessment, parse_assessment
from .config import Config
from .diff import ChangeTarget, extract_targets, git_diff
from .execute import Worktree, differential_check
from .ledger import Candidate, Ledger
from .llm import BaseLLM, BudgetExceeded, LLMError, strip_code_fence
from .risk import RiskScore, rank
from .safety import check_candidate

__all__ = ["Finding", "Report", "run", "import_path_for", "existing_tests_for"]


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
    duration_s: float = 0.0
    reruns: int = 2
    errors: list[str] = field(default_factory=list)
    version: str = __version__

    @property
    def has_regression(self) -> bool:
        return any(f.assessment.should_report for f in self.findings)

    @property
    def cost_line(self) -> str:
        if not self.priced:
            return "cost not priced for this model"
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
            "duration_s": round(self.duration_s, 2),
            "has_regression": self.has_regression,
            "errors": self.errors,
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


def import_path_for(file_path: str) -> str:
    """Best-effort module path. A wrong guess shows up as a collection error,
    which the oracle discards, which is the correct failure mode."""
    p = file_path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    if parts and parts[0] in ("src", "lib", "python"):
        parts = parts[1:]
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def existing_tests_for(repo: Path, symbol: str, limit: int = 8) -> list[str]:
    """Test files that already mention this symbol, so we do not duplicate them."""
    leaf = symbol.split(".")[-1]
    if not leaf or leaf == "<module>":
        return []
    hits: list[str] = []
    for path in list(Path(repo).rglob("test_*.py"))[:800]:
        try:
            if leaf in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(path.relative_to(repo)))
        except (OSError, ValueError):
            continue
        if len(hits) >= limit:
            break
    return hits


def _added_excerpt(t: ChangeTarget, limit: int = 40) -> str:
    lines = t.source_after.splitlines()
    offset = t.start_line
    picked = [f"{n}: {lines[n - offset]}"
              for n in t.added_lines[:limit]
              if 0 <= n - offset < len(lines)]
    return "\n".join(picked) or "(no line-level detail available)"


def _repro(base: str, head: str, file_hint: str) -> str:
    return (f"git checkout {head[:12]} && pytest {file_hint} -q   # expect FAIL\n"
            f"git checkout {base[:12]} && pytest {file_hint} -q   # expect PASS")


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def run(
    repo: Path | str,
    base: str,
    head: str,
    cfg: Config,
    llm: BaseLLM,
    pr_title: str = "",
    pr_body: str = "",
    pr_ref: str = "",
    ledger: Ledger | None = None,
    on_event=None,
) -> Report:
    started = time.time()
    repo = Path(repo).resolve()
    report = Report(repo=repo.name, base=base, head=head, model=llm.model,
                    reruns=cfg.reruns)

    def emit(message: str) -> None:
        if on_event:
            on_event(message)

    diff_text = git_diff(repo, base, head)
    if not diff_text.strip():
        report.errors.append("empty diff between base and head")
        report.duration_s = time.time() - started
        return report

    all_targets = extract_targets(diff_text, repo=repo, base=base, head=head)
    kept = [t for t in all_targets if not cfg.is_ignored(t.file_path)]
    report.targets_skipped = len(all_targets) - len(kept)

    ranked: list[RiskScore] = rank(kept, cfg.risk_threshold, cfg.max_targets)
    report.targets_considered = len(ranked)
    emit(f"{len(all_targets)} changed symbol(s), {len(ranked)} above risk threshold")

    if not ranked:
        report.duration_s = time.time() - started
        return report

    owns_ledger = ledger is None
    ledger = ledger or Ledger(repo / cfg.ledger_path)

    try:
        with ExitStack() as stack:
            head_dir = stack.enter_context(Worktree(repo, head))
            base_dir = stack.enter_context(Worktree(repo, base))

            for rs in ranked:
                t = rs.target
                emit(f"target {t.qualified} (risk {rs.score:.2f})")
                found = False
                for attempt in range(1, cfg.candidates_per_target + 1):
                    if found:
                        break
                    try:
                        raw = llm.complete(
                            P.GENERATOR_SYSTEM,
                            P.GENERATOR_USER.format(
                                repo_name=repo.name,
                                file_path=t.file_path,
                                symbol=t.symbol,
                                import_path=import_path_for(t.file_path),
                                risk_reasons=", ".join(rs.reasons) or "none",
                                source_before=t.source_before or "(new code, no prior version)",
                                source_after=t.source_after,
                                added_excerpt=_added_excerpt(t),
                                existing_tests_block=P.existing_tests_block(
                                    existing_tests_for(repo, t.symbol)),
                                pr_context_block=P.pr_context_block(pr_title, pr_body),
                                attempt=attempt,
                                total_attempts=cfg.candidates_per_target,
                            ),
                            n=1,
                            temperature=min(1.0, cfg.temperature + 0.05 * (attempt - 1)),
                        )[0]
                    except BudgetExceeded as exc:
                        report.errors.append(str(exc))
                        emit("budget exhausted, stopping generation")
                        break
                    except LLMError as exc:
                        report.errors.append(f"model error: {exc}")
                        _bump(report.discarded, "model_error")
                        continue

                    code = strip_code_fence(raw)
                    if not code or P.NO_CANDIDATE in code:
                        _bump(report.discarded, "model_declined")
                        continue

                    report.candidates_generated += 1
                    check = check_candidate(code)
                    if not check.ok:
                        _bump(report.discarded, f"unsafe_or_invalid: {check.reason}")
                        continue

                    verdict = differential_check(
                        repo, base, head, code,
                        timeout_s=cfg.timeout_s, reruns=cfg.reruns,
                        head_workdir=head_dir, base_workdir=base_dir,
                    )

                    cand = Candidate(
                        repo=str(repo.name), pr=pr_ref, base_rev=base, head_rev=head,
                        file_path=t.file_path, symbol=t.symbol,
                        risk_score=rs.score, risk_reasons=rs.reasons,
                        model=llm.model, attempt=attempt, test_code=code,
                        oracle_catching=verdict.is_catching,
                        oracle_reason=verdict.reason, latent=verdict.latent,
                        cost_usd=round(llm.usage.cost_usd, 6),
                    )

                    if not verdict.is_catching:
                        _bump(report.discarded, verdict.reason)
                        if verdict.latent and cfg.latent_mode:
                            finding = Finding(
                                target=t, test_code=code,
                                oracle_reason=verdict.reason,
                                failure_excerpt=verdict.failure_excerpt,
                                assessment=Assessment(
                                    verdict="unclear", confidence=0.0,
                                    summary="fails on base as well: pre-existing fault"),
                                risk_score=rs.score, risk_reasons=rs.reasons,
                                repro_command=_repro(base, head, t.file_path),
                                latent=True,
                            )
                            finding.ledger_id = ledger.record(cand)
                            report.latent_findings.append(finding)
                        else:
                            ledger.record(cand)
                        continue

                    # Proven catching. Now, and only now, ask whether a human cares.
                    try:
                        payload = llm.complete_json(
                            P.ASSESSOR_SYSTEM,
                            P.ASSESSOR_USER.format(
                                pr_title=pr_title or "(none)",
                                pr_body=(pr_body or "(none)")[:1500],
                                file_path=t.file_path, symbol=t.symbol,
                                source_before=t.source_before or "(new code)",
                                source_after=t.source_after,
                                test_code=code,
                                failure_excerpt=verdict.failure_excerpt[:2000],
                            ),
                            temperature=0.0,
                        )
                        assessment = parse_assessment(payload)
                    except (LLMError, BudgetExceeded) as exc:
                        report.errors.append(f"assessor unavailable: {exc}")
                        assessment = Assessment(
                            verdict="unclear", confidence=0.0,
                            summary="assessor did not run; the oracle result stands")

                    cand.assess_verdict = assessment.verdict
                    cand.assess_conf = assessment.confidence
                    cand.assess_summary = assessment.summary
                    cand.reported = assessment.should_report

                    finding = Finding(
                        target=t, test_code=code, oracle_reason=verdict.reason,
                        failure_excerpt=verdict.failure_excerpt,
                        assessment=assessment, risk_score=rs.score,
                        risk_reasons=rs.reasons,
                        repro_command=_repro(base, head, t.file_path),
                    )
                    finding.ledger_id = ledger.record(cand)
                    report.findings.append(finding)
                    found = True
                    emit(f"  catching test found ({assessment.badge})")
    finally:
        report.cost_usd = llm.usage.cost_usd
        report.priced = llm.usage.priced
        report.duration_s = time.time() - started
        if owns_ledger:
            ledger.close()

    return report
