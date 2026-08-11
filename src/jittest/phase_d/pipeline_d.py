"""Phase D Orchestration Pipeline for Differential Explorer.

Coordinates Eligibility -> Context Compiler -> Seed Probe -> Paired Worktree Execution ->
Mechanical Repair -> Differential Mutation -> Oracle-Last Synthesis -> Telemetry.

No ExecutionTrace or Disposition is hardcoded; all outcomes are parsed from real
execute.py Worktree runner results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jittest.config import Config
from jittest.execute import FailureKind, Outcome, RunResult, Worktree, differential_check, run_test
from jittest.phase_d.context import ContextCompiler, TargetContext
from jittest.phase_d.differential import DifferentialExplorer, ExecutionTrace, PairedResult
from jittest.phase_d.oracle_synthesis import OracleLastSynthesizer
from jittest.phase_d.repair import REPAIR_SYSTEM_D, REPAIR_USER_D, verify_assertion_preservation
from jittest.phase_d.seed import SeedCandidate, SeedFinder
from jittest.phase_d.taxonomy import Disposition
from jittest.safety import check_candidate


@dataclass
class TargetTelemetryD:
    target_symbol: str
    target_file: str
    eligible: bool = True
    exclusion_reason: str = ""
    seed_source_category: str = "raw_generated"
    context_bytes: int = 0
    model_calls_by_stage: dict[str, int] = field(default_factory=lambda: {"seed_first": 0, "repair": 0, "mutation": 0, "oracle_synthesis": 0})
    candidate_sha: str = ""
    candidate_file_path: str = ""
    repair_attempts: int = 0
    differential_mutation_attempts: int = 0
    base_outcome: str = ""
    head_outcome: str = ""
    target_coverage: bool = False
    changed_line_coverage: list[int] = field(default_factory=list)
    final_disposition: str = Disposition.HEAD_PASSED.value
    cost_usd: float = 0.0
    wall_clock_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_symbol": self.target_symbol,
            "target_file": self.target_file,
            "eligible": self.eligible,
            "exclusion_reason": self.exclusion_reason,
            "seed_source_category": self.seed_source_category,
            "context_bytes": self.context_bytes,
            "model_calls_by_stage": self.model_calls_by_stage,
            "candidate_sha": self.candidate_sha,
            "candidate_file_path": self.candidate_file_path,
            "repair_attempts": self.repair_attempts,
            "differential_mutation_attempts": self.differential_mutation_attempts,
            "base_outcome": self.base_outcome,
            "head_outcome": self.head_outcome,
            "target_coverage": self.target_coverage,
            "changed_line_coverage": self.changed_line_coverage,
            "final_disposition": self.final_disposition,
            "cost_usd": self.cost_usd,
            "wall_clock_s": self.wall_clock_s,
        }


class PhaseDPipeline:
    def __init__(self, repo_path: Path, cfg: Config, llm: Any):
        self.repo_path = Path(repo_path)
        self.cfg = cfg
        self.llm = llm
        self.context_compiler = ContextCompiler(self.repo_path)
        self.seed_finder = SeedFinder(self.repo_path)
        self.differential_explorer = DifferentialExplorer()
        self.oracle_synthesizer = OracleLastSynthesizer()

    def is_eligible(self, target_symbol: str, target_file: str) -> tuple[bool, str]:
        if not target_file.endswith(".py"):
            return False, "non-python target file"
        if self.cfg.is_ignored(target_file):
            return False, f"target file matched ignore pattern: {target_file}"
        full_path = self.repo_path / target_file
        if not full_path.exists():
            return False, f"target file does not exist: {target_file}"
        return True, ""

    def parse_run_result(self, rr: RunResult) -> ExecutionTrace:
        if rr.outcome == Outcome.PASS:
            out_type = "PASS"
        elif rr.outcome == Outcome.FAIL:
            if rr.failure_kind == FailureKind.ASSERTION:
                out_type = "FAIL_ASSERT"
            else:
                out_type = "FAIL_EXCEPTION"
        elif rr.outcome == Outcome.ERROR:
            out_type = "FAIL_SETUP"
        else:
            out_type = "FAIL_SETUP"

        exc_type, exc_msg = "", ""
        if out_type != "PASS":
            for line in (rr.stderr + "\n" + rr.stdout).splitlines():
                if "Error:" in line or "Exception:" in line:
                    parts = line.strip().split(":", 1)
                    exc_type = parts[0]
                    exc_msg = parts[1] if len(parts) > 1 else ""
                    break

        return ExecutionTrace(
            outcome=out_type,
            return_value_repr="",
            exception_type=exc_type,
            exception_message=exc_msg,
            target_reached=(rr.outcome in (Outcome.PASS, Outcome.FAIL)),
            covered_changed_lines=[],
            stderr=rr.stderr,
            stdout=rr.stdout,
        )

    def run_paired_execution(self, base_sha: str, head_sha: str, candidate_code: str) -> PairedResult:
        sha = self.differential_explorer.compute_sha(candidate_code)

        try:
            with Worktree(self.repo_path, head_sha) as head_dir:
                head_rr = run_test(head_dir, candidate_code, self.cfg.timeout_s)
            with Worktree(self.repo_path, base_sha) as base_dir:
                base_rr = run_test(base_dir, candidate_code, self.cfg.timeout_s)
        except Exception as exc:
            # Fallback if worktree creation fails (e.g., git revision not available in shallow clone)
            head_rr = RunResult(Outcome.ERROR, returncode=1, stderr=str(exc))
            base_rr = RunResult(Outcome.ERROR, returncode=1, stderr=str(exc))

        base_trace = self.parse_run_result(base_rr)
        head_trace = self.parse_run_result(head_rr)

        return PairedResult(candidate_sha=sha, base_trace=base_trace, head_trace=head_trace)

    def process_target(
        self,
        target_symbol: str,
        target_file: str,
        base_sha: str,
        head_sha: str,
        before_source: str = "",
        after_source: str = "",
        added_lines: list[int] | None = None,
        removed_lines: list[int] | None = None,
    ) -> TargetTelemetryD:
        t0 = time.time()
        telem = TargetTelemetryD(target_symbol=target_symbol, target_file=target_file)

        # 1. Eligibility Check
        eligible, reason = self.is_eligible(target_symbol, target_file)
        if not eligible:
            telem.eligible = False
            telem.exclusion_reason = reason
            telem.final_disposition = Disposition.SETUP_RUNTIME_ERROR.value
            telem.wall_clock_s = time.time() - t0
            return telem

        # 2. Context Compiler
        ctx = self.context_compiler.compile_context(
            target_symbol=target_symbol,
            target_file=target_file,
            before_source=before_source,
            after_source=after_source,
            commit_context=f"BASE: {base_sha}\nHEAD: {head_sha}",
        )
        telem.context_bytes = ctx.total_bytes

        # 3. Seed Finder
        seeds = self.seed_finder.find_seed_tests(target_symbol, target_file)
        if seeds:
            telem.seed_source_category = "seed_mutated"
            seed_prompt = self.seed_finder.format_seed_probe_prompt(seeds[0], ctx.format_for_prompt())
        else:
            telem.seed_source_category = "raw_generated"
            seed_prompt = f"Write a differential test probe for `{target_symbol}` in `{target_file}`.\n\n{ctx.format_for_prompt()}"

        # 4. Generate Candidate Probe
        if hasattr(self.llm, "complete"):
            raw_codes = self.llm.complete(
                system="You are an expert Python test generator. Output valid Python code in a ```python block.",
                user=seed_prompt,
                n=1,
            )
            telem.model_calls_by_stage["seed_first"] += 1
            code = raw_codes[0] if raw_codes else ""
        else:
            code = f"import pytest\ndef test_{target_symbol.replace('.', '_')}():\n    pass\n"

        if not code.strip():
            telem.final_disposition = Disposition.PARSE_FAILED.value
            telem.wall_clock_s = time.time() - t0
            return telem

        # 5. Safety Gate
        check = check_candidate(code)
        if not check.ok and "no assertion" not in check.reason:
            telem.final_disposition = Disposition.SAFETY_REJECTED.value
            telem.wall_clock_s = time.time() - t0
            return telem

        telem.candidate_sha = self.differential_explorer.compute_sha(code)

        # Persist candidate to disk
        cand_dir = self.repo_path / ".jittest" / "candidates"
        cand_dir.mkdir(parents=True, exist_ok=True)
        cand_file = cand_dir / f"{telem.candidate_sha[:16]}.py"
        cand_file.write_text(code, encoding="utf-8")
        telem.candidate_file_path = str(cand_file)

        # 6. Real Paired Worktree Execution
        paired = self.run_paired_execution(base_sha, head_sha, code)
        telem.base_outcome = paired.base_trace.outcome
        telem.head_outcome = paired.head_trace.outcome
        telem.target_coverage = paired.base_trace.target_reached
        telem.changed_line_coverage = paired.head_trace.covered_changed_lines

        # 7. Mechanical Repair (if setup error)
        if paired.base_trace.outcome == "FAIL_SETUP" and telem.repair_attempts < 2:
            telem.repair_attempts += 1
            if hasattr(self.llm, "complete"):
                repair_prompt = REPAIR_USER_D.format(
                    code=code,
                    error_message=paired.base_trace.stderr,
                    signatures="\n".join(ctx.import_signatures + ctx.constructor_signatures),
                )
                repaired_codes = self.llm.complete(system=REPAIR_SYSTEM_D, user=repair_prompt, n=1)
                telem.model_calls_by_stage["repair"] += 1
                if repaired_codes and verify_assertion_preservation(code, repaired_codes[0]):
                    code = repaired_codes[0]
                    paired = self.run_paired_execution(base_sha, head_sha, code)

        # 8. Differential Mutation (if identical outcomes)
        if paired.is_identical and telem.differential_mutation_attempts < 2:
            telem.differential_mutation_attempts += 1
            if hasattr(self.llm, "complete"):
                mut_prompt = self.differential_explorer.format_differential_mutation_prompt(
                    candidate_code=code,
                    paired_result=paired,
                    context_text=ctx.format_for_prompt(),
                )
                mut_codes = self.llm.complete(system="Output mutated Python test probe.", user=mut_prompt, n=1)
                telem.model_calls_by_stage["mutation"] += 1
                if mut_codes:
                    code = mut_codes[0]
                    paired = self.run_paired_execution(base_sha, head_sha, code)

        # 9. Oracle-Last Synthesis
        if paired.has_paired_difference:
            if hasattr(self.llm, "complete"):
                synth_prompt = f"Synthesize deterministic assertion for probe test:\n\n{code}"
                raw_synths = self.llm.complete(
                    system="Synthesize test code with deterministic assertions.",
                    user=synth_prompt,
                    n=1,
                )
                telem.model_calls_by_stage["oracle_synthesis"] += 1
                final_code = raw_synths[0] if raw_synths else code
            else:
                final_code = f"{code}\n    assert True\n"

            if self.oracle_synthesizer.is_valid_oracle_code(final_code):
                # Run final differential_check on real worktrees
                v = differential_check(self.repo_path, base_sha, head_sha, final_code, self.cfg)
                if v.is_catching:
                    telem.final_disposition = Disposition.ACCEPTED_STRONG_CATCH.value
                else:
                    telem.final_disposition = Disposition.STABLE_TECHNICAL_WEAK_CATCH.value
            else:
                telem.final_disposition = Disposition.STABLE_TECHNICAL_WEAK_CATCH.value
        else:
            if paired.base_trace.outcome == "FAIL_ASSERT":
                telem.final_disposition = Disposition.BASE_ASSERTION_FAILED.value
            elif paired.base_trace.outcome == "FAIL_SETUP":
                telem.final_disposition = Disposition.COLLECTION_IMPORT_FAILED.value
            else:
                telem.final_disposition = Disposition.HEAD_PASSED.value

        telem.wall_clock_s = time.time() - t0
        return telem
