"""Small pure helpers for the pipeline: paths, excerpts, telemetry emission."""
from __future__ import annotations

from pathlib import Path

from .diff import ChangeTarget
from .results import CandidateTelemetry

__all__ = ["import_path_for", "existing_tests_for", "_added_excerpt", "_repro",
           "_bump", "_disposition_from_verdict", "_telemetry"]


def import_path_for(file_path: str) -> str:
    """Best-effort module path. A wrong guess shows up as a collection error,
    which the oracle discards, which is the correct failure mode."""
    p = file_path.replace(chr(92) * 2, "/")
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
    return chr(10).join(picked) or "(no line-level detail available)"


def _repro(base: str, head: str, file_hint: str) -> str:
    return (f"git checkout {head[:12]} && pytest {file_hint} -q   # expect FAIL" + chr(10) +
            f"git checkout {base[:12]} && pytest {file_hint} -q   # expect PASS")


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _disposition_from_verdict(verdict) -> str:
    """Read the disposition the oracle stated. Defect 38.

    This used to search verdict.reason for substrings such as "could not be
    collected", which made a human-readable sentence into a machine interface.
    Rewording the sentence silently relabelled telemetry, and every ending that
    no substring distinguished - no test executed on base, a provenance
    mismatch, a timeout - fell through to "fails on base too", which is a
    different and far less alarming claim than what actually happened.
    """
    disposition = getattr(verdict, "disposition", None)
    if disposition is None:
        raise ValueError("verdict carries no disposition")
    return str(disposition)


def _telemetry(report, target, rs, attempt, disposition,
               verdict=None, assessment=None) -> None:
    """Emit one structured telemetry line and append to report.telemetry."""
    head_out = ""
    base_out = ""
    rerun_agree = True
    excerpt = ""

    if verdict is not None:
        head_out = verdict.head_outcome.value if verdict.head_outcome else ""
        base_out = verdict.base_outcome.value if verdict.base_outcome else ""
        # Defect 39. Derived from the recorded per-execution outcomes rather
        # than from whether the reason string happens to contain a word.
        rerun_agree = verdict.rerun_agreement
        excerpt = chr(10).join(verdict.failure_excerpt.splitlines()[:5])

    assess_v = ""
    assess_c = 0.0
    if assessment is not None:
        assess_v = assessment.verdict
        assess_c = assessment.confidence

    tel = CandidateTelemetry(
        target_symbol=target.symbol,
        target_file=target.file_path,
        risk_score=rs.score,
        candidate_index=attempt,
        disposition=disposition,
        head_outcome=head_out,
        base_outcome=base_out,
        rerun_agreement=rerun_agree,
        assessor_verdict=assess_v,
        assessor_confidence=assess_c,
        failure_excerpt=excerpt,
    )
    report.telemetry.append(tel)
    # Emit structured line to stderr (visible in workflow logs)
    print(f"  telemetry: {tel.as_jsonl()}", flush=True)
