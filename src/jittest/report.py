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


def _fence(code: str, lang: str = "python") -> str:
    return f"```{lang}\n{code.strip()}\n```"


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
            out.append(f"**{f.assessment.summary}**")
        if f.assessment.reviewer_question:
            out.append(f"> {f.assessment.reviewer_question}")
        out.append(
            f"<sub>assessor: {f.assessment.badge} "
            f"(confidence {f.assessment.confidence:.2f}, "
            f"severity {f.assessment.severity}) - risk score "
            f"{f.risk_score:.2f} [{', '.join(f.risk_reasons) or 'none'}]</sub>"
        )
        out.append("")
        out.append(_fence(f.test_code))
        out.append("<details><summary>Failure output on head</summary>")
        out.append("")
        out.append(_fence(f.failure_excerpt or "(no output captured)", "text"))
        out.append("</details>")
        out.append("<details><summary>Reproduce locally</summary>")
        out.append("")
        out.append(_fence(f.repro_command, "bash"))
        out.append("</details>")

    if low:
        out.append("")
        out.append(f"<details><summary>{len(low)} proven failure"
                   f"{'s' if len(low) != 1 else ''} the assessor could not "
                   "confidently call a regression</summary>")
        out.append("")
        for f in low:
            out.append(f"- `{f.target.qualified}` - {f.assessment.badge} "
                       f"(confidence {f.assessment.confidence:.2f}). "
                       f"{f.assessment.summary}")
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
    out.append(
        f"<sub>{report.targets_considered} changed symbol(s) analysed, "
        f"{report.candidates_generated} candidate(s) generated, "
        f"{report.candidates_generated - len(report.findings)} discarded by the "
        f"oracle. {report.cost_line} - {report.duration_s:.0f}s. "
        f"jittest v{report.version}, model `{report.model}`.</sub>"
    )
    if report.errors:
        out.append(f"<sub>Non-fatal issues: {'; '.join(report.errors[:3])}</sub>")
    return "\n".join(out)


def to_terminal(report) -> str:
    lines: list[str] = []
    lines.append(f"jittest v{report.version}  {report.base[:8]}...{report.head[:8]}")
    lines.append(
        f"  {report.targets_considered} symbol(s) analysed | "
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
