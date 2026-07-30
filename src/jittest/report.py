"""Report rendering.

Two rules, both learned from watching AI review bots get muted:

  1. If there is nothing proven, say nothing. jittest posts no comment at all
     when it finds no catching test. Silence is a feature.
  2. Every claim is reproducible in one command, printed next to the claim. A
     reviewer must never have to take our word for anything.
"""
from __future__ import annotations

MARKER = "<!-- jittest-report -->"

__all__ = ["MARKER", "to_markdown", "to_terminal", "summary_line"]


def _untrusted(text: str, limit: int = 2000) -> str:
    """Neutralise model-authored or program-captured text before embedding it.

    Defect 31. Everything rendered from an assessment summary, a reviewer
    question, or captured pytest output is untrusted: the assessor is a language
    model reading a diff and a PR body that anyone can write. If such text
    contains the literal upsert marker, the posted comment ends up with several
    markers, and `upsert_pr_comment` can no longer tell which comment is ours -
    so a crafted PR body could make jittest edit the wrong comment, or orphan
    its own. HTML comment delimiters are also broken up so injected text cannot
    comment out the rest of the report.

    The marker is kept human-readable rather than stripped, so a reviewer can
    still see what the model tried to emit.
    """
    if not text:
        return ""
    clean = str(text)
    clean = clean.replace(MARKER, "(jittest-report marker removed)")
    clean = clean.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    if len(clean) > limit:
        clean = clean[:limit] + " ...(truncated)"
    return clean


def _fence(code: str, lang: str = "python") -> str:
    """Fence a block, widening the fence so embedded backticks cannot escape it."""
    body = str(code).strip()
    longest = 0
    run = 0
    for ch in body:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{body}\n{fence}"


def summary_line(report) -> str:
    n = len(report.findings)
    if n == 0:
        return "no catching tests found"
    return f"{n} proven catching test{'s' if n != 1 else ''}"


def to_markdown(report, include_empty: bool = False) -> str:
    high = [f for f in report.findings if f.assessment.should_report]
    low = [f for f in report.findings if not f.assessment.should_report]

    if not report.findings and not include_empty:
        return ""

    out: list[str] = [MARKER]
    if high:
        out.append(f"### jittest: {len(high)} likely regression"
                   f"{'s' if len(high) != 1 else ''} on this PR")
    elif low:
        out.append("### jittest: findings need a human call")
    else:
        out.append("### jittest: no catching test found")

    out.append(
        "Each finding below is a test that **passes on "
        f"`{report.base[:12]}` and fails on `{report.head[:12]}`**, rerun "
        f"{report.reruns} times to rule out flakiness. jittest does not report "
        "tests that merely pass on your new code."
    )

    for i, f in enumerate(high, 1):
        out.append("")
        out.append(f"#### {i}. `{f.target.qualified}`")
        if f.assessment.summary:
            out.append(f"**{_untrusted(f.assessment.summary, 600)}**")
        if f.assessment.reviewer_question:
            question = _untrusted(f.assessment.reviewer_question, 600)
            # A multi-line question would break out of the block quote.
            out.append("> " + question.replace("\n", " "))
        reasons = ", ".join(_untrusted(r, 120) for r in f.risk_reasons)
        out.append(
            f"<sub>assessor: {_untrusted(f.assessment.badge, 40)} "
            f"(confidence {f.assessment.confidence:.2f}, "
            f"severity {_untrusted(f.assessment.severity, 40)}) - risk score "
            f"{f.risk_score:.2f} [{reasons or 'none'}]</sub>"
        )
        out.append("")
        out.append(_fence(f.test_code))
        out.append("<details><summary>Failure output on head</summary>")
        out.append("")
        out.append(_fence(
            _untrusted(f.failure_excerpt, 2000) or "(no output captured)", "text"))
        out.append("</details>")
        out.append("<details><summary>Reproduce locally</summary>")
        out.append("")
        out.append(_fence(_untrusted(f.repro_command, 600), "bash"))
        out.append("</details>")

    if low:
        out.append("")
        out.append(f"<details><summary>{len(low)} proven failure"
                   f"{'s' if len(low) != 1 else ''} the assessor could not "
                   "confidently call a regression</summary>")
        out.append("")
        for f in low:
            out.append(f"- `{f.target.qualified}` - {_untrusted(f.assessment.badge, 40)} "
                       f"(confidence {f.assessment.confidence:.2f}). "
                       f"{_untrusted(f.assessment.summary, 400)}")
        out.append("</details>")

    if report.latent_findings:
        out.append("")
        out.append(f"<details><summary>{len(report.latent_findings)} pre-existing "
                   "fault(s): failed on base as well, so not caused by this PR"
                   "</summary>")
        out.append("")
        for lf in report.latent_findings:
            out.append(f"- `{lf.target.qualified}`")
        out.append("</details>")

    out.append("")
    funnel_total = (report.targets_considered + report.targets_filtered
                    + report.targets_skipped)
    out.append(
        f"<sub>{report.targets_considered} of {funnel_total} changed symbol(s) "
        f"analysed ({report.targets_filtered} below the risk threshold, "
        f"{report.targets_skipped} ignored by rule), "
        f"{report.candidates_generated} candidate(s) generated, "
        f"{report.candidates_generated - len(report.findings)} discarded by the "
        f"oracle. {report.cost_line} - {report.duration_s:.0f}s. "
        f"jittest v{report.version}, model `{report.model}`.</sub>"
    )
    if report.errors:
        issues = "; ".join(_untrusted(e, 300) for e in report.errors[:3])
        out.append(f"<sub>Non-fatal issues: {issues}</sub>")

    rendered = "\n".join(out)
    # Structural invariant: exactly one marker, always the first thing in the
    # comment. If this ever fails, upsert would target the wrong comment.
    assert rendered.count(MARKER) == 1, "report must contain exactly one marker"
    return rendered


def to_terminal(report) -> str:
    lines: list[str] = []
    lines.append(f"jittest v{report.version}  {report.base[:8]}...{report.head[:8]}")
    funnel_total = (report.targets_considered + report.targets_filtered
                    + report.targets_skipped)
    lines.append(
        f"  {report.targets_considered}/{funnel_total} symbol(s) analysed "
        f"({report.targets_filtered} below threshold, "
        f"{report.targets_skipped} ignored) | "
        f"{report.candidates_generated} candidate(s) | "
        f"{len(report.findings)} catching | {report.cost_line}"
    )
    if not report.findings:
        lines.append("  No catching test found. That is a normal and common result.")
    for f in report.findings:
        mark = "REGRESSION" if f.assessment.should_report else f.assessment.badge.upper()
        lines.append("")
        lines.append(f"  [{mark}] {f.target.qualified}")
        if f.assessment.summary:
            lines.append(f"    {f.assessment.summary}")
        lines.append(f"    oracle: {f.oracle_reason}")
        lines.append(f"    reproduce: {f.repro_command}")
    for e in report.errors:
        lines.append(f"  note: {e}")
    return "\n".join(lines)
