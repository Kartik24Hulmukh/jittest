"""Orchestration: diff in, proven catching tests out. Worktrees are created
once per run and reused, which is what three executions per candidate affords.
"""
from __future__ import annotations

import time
from contextlib import ExitStack
from pathlib import Path

from . import prompts as P
from ._pipeline_helpers import (
    _added_excerpt,
    _bump,
    _disposition_from_verdict,
    _repro,
    _telemetry,
    existing_tests_for,
    import_path_for,
    parse_failure_digest,
)
from .assess import Assessment, parse_assessment
from .config import Config
from .diff import GitError, extract_targets, git_diff
from .execute import Worktree, differential_check
from .ledger import Candidate, Ledger
from .llm import (
    BaseLLM,
    BudgetExceeded,
    LLMError,
    RateLimitedError,
    TimedOutError,
    strip_code_fence,
)
from .results import DISPOSITIONS, CandidateTelemetry, Finding, Report
from .risk import RiskScore, rank
from .safety import check_candidate
from .sandbox import SandboxUnavailable
from .sandbox import plan as sandbox_plan

__all__ = ["Finding", "Report", "CandidateTelemetry", "run", "DISPOSITIONS",
           "import_path_for", "existing_tests_for"]


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

    try:
        diff_text = git_diff(repo, base, head)
    except GitError as exc:
        report.diff_status = "git_failed"
        report.errors.append(str(exc))
        report.model_requests = llm.usage.calls
        report.duration_s = time.time() - started
        return report

    if not diff_text.strip():
        report.diff_status = "empty"
        report.errors.append(
            "empty diff between base and head: no changed Python symbols were "
            "found, so no test could be generated. This is a property of the "
            "revision pair, not a result about the code.")
        report.model_requests = llm.usage.calls
        report.duration_s = time.time() - started
        return report

    all_targets = extract_targets(diff_text, repo=repo, base=base, head=head)
    kept = [t for t in all_targets if not cfg.is_ignored(t.file_path)]
    report.targets_skipped = len(all_targets) - len(kept)

    ranked: list[RiskScore] = rank(kept, cfg.risk_threshold, cfg.max_targets)
    report.targets_considered = len(ranked)
    emit(f"{len(all_targets)} changed symbol(s), {len(ranked)} above risk threshold")

    if not ranked:
        # "Analysed nothing" must never wear the words of "found nothing".
        if all_targets and not kept:
            report.diff_status = "all_targets_ignored"
            report.errors.append(
                f"all {len(all_targets)} changed symbol(s) matched an ignore "
                f"pattern, so nothing was analysed. This is a fact about the "
                f"`ignore` configuration, not about the code.")
        elif kept:
            report.diff_status = "below_risk_threshold"
            report.errors.append(
                f"{len(kept)} changed symbol(s) were all scored below the risk "
                f"threshold of {cfg.risk_threshold}, so nothing was analysed. "
                f"Lower `risk_threshold` to widen the net.")
        elif not all_targets:
            import subprocess
            res = subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", head, base],
                capture_output=True
            )
            has_py = any(
                line.startswith("diff --git a/") and line.strip().endswith(".py")
                for line in diff_text.splitlines()
            )
            if res.returncode == 0:
                report.diff_status = "inverted_range"
                report.errors.append("head revision is an ancestor of base (inverted revision range).")
            elif not has_py:
                report.diff_status = "no_python_in_diff"
                report.errors.append("diff contains no changed Python files.")
            else:
                report.diff_status = "no_targets_after_ranking"
                report.errors.append("no changed Python functions or classes were extracted from diff.")
        report.model_requests = llm.usage.calls
        report.duration_s = time.time() - started
        return report


    # Decided once up front: "required" raises rather than running unconfined.
    try:
        sbx = sandbox_plan(cfg.sandbox_mode, cfg.sandbox_backend, cfg.sandbox_image)
    except SandboxUnavailable as exc:
        report.diff_status = "sandbox_unavailable"
        report.errors.append(str(exc))
        report.model_requests = llm.usage.calls
        report.duration_s = time.time() - started
        return report
    report.sandbox = sbx.as_dict()
    for note in sbx.notes:
        emit(note)
        if not sbx.isolated:
            report.errors.append(note)

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
                    except RateLimitedError as exc:
                        report.errors.append(f"rate limited: {exc}")
                        _bump(report.discarded, "rate_limited")
                        _telemetry(report, t, rs, attempt, "rate_limited",
                                   check_reason=str(exc))
                        continue
                    except TimedOutError as exc:
                        report.errors.append(f"timed out: {exc}")
                        _bump(report.discarded, "timed_out")
                        _telemetry(report, t, rs, attempt, "timed_out",
                                   check_reason=str(exc))
                        continue
                    except LLMError as exc:
                        report.errors.append(f"model error: {exc}")
                        _bump(report.discarded, "model_error")
                        continue

                    code = strip_code_fence(raw)
                    if not code or P.NO_CANDIDATE in code:
                        _bump(report.discarded, "model_declined")
                        _telemetry(report, t, rs, attempt, "model_declined")
                        remaining = cfg.candidates_per_target - attempt
                        if remaining > 0:
                            _bump(report.discarded, "model_declined_short_circuit", count=remaining)
                        break


                    import ast as _ast
                    try:
                        _ast.parse(code)
                    except SyntaxError as exc:
                        # Track C3. Record the SHAPE of the failure, never the
                        # text: an unparsable response is still model-authored
                        # code about the user's source, and telemetry is
                        # attached to public workflow runs.
                        digest = parse_failure_digest(code, exc)
                        _bump(report.discarded, "parse_failed")
                        _telemetry(report, t, rs, attempt, "parse_failed",
                                   parse_error=digest)
                        continue

                    report.candidates_generated += 1
                    check = check_candidate(code)
                    if not check.ok:
                        # Track C3. check.reason was already in the discarded
                        # histogram key; it was missing from the telemetry the
                        # eval harness actually parses, which is why seven
                        # rejections from the only completed run cannot be
                        # explained after the fact.
                        _bump(report.discarded, f"unsafe_or_invalid: {check.reason}")
                        _telemetry(report, t, rs, attempt, "safety_rejected",
                                   check_reason=check.reason)
                        continue

                    verdict = differential_check(
                        repo, base, head, code,
                        timeout_s=cfg.timeout_s, reruns=cfg.reruns,
                        head_workdir=head_dir, base_workdir=base_dir,
                        sbx=sbx,
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
                        disp = _disposition_from_verdict(verdict)
                        _telemetry(report, t, rs, attempt, disp,
                                   verdict=verdict)
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
                    _telemetry(report, t, rs, attempt, "catching",
                               verdict=verdict, assessment=assessment)
                    emit(f"  catching test found ({assessment.badge})")
    finally:
        report.cost_usd = llm.usage.cost_usd
        report.priced = llm.usage.priced
        report.tokens_estimated = llm.usage.tokens_estimated
        report.input_tokens = llm.usage.input_tokens
        report.output_tokens = llm.usage.output_tokens
        report.model_requests = llm.usage.calls
        report.duration_s = time.time() - started
        if owns_ledger:
            ledger.close()

    return report
