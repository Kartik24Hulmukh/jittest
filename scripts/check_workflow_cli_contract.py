#!/usr/bin/env python3
"""Statically prove every workflow `run:` step calls a repo Python script the way
that script's argparse contract allows.

Motivation (PR #208, 2026-09-15): `.github/workflows/eval.yml` invoked
`eval/run_bugsinpy.py` without its `required=True` flag `--bugsinpy` and let
`--out` fall back to `eval-results.json` while the job uploaded and asserted
`results.json`. Every funded dispatch died in 0 s at argument parsing, and a
passing sweep would have produced an empty artifact. Nothing in CI could see it
because the contract between a workflow and a CLI was never checked, only run.

This checker closes that class:

* every `python <eval|scripts>/x.py ...` line in every workflow is located;
* the script's `add_argument(...)` calls are read via `ast` (no import, no
  execution): option strings, `required=True`, `default=`;
* violations: a required flag missing from the literal command line, a flag
  the script does not define, or an `--out` value that a later step of the
  same job never references while it does reference some other `*.json`.

Exit 0 when clean, 1 on any violation. Pure functions, used by the launch gate.
Stdlib only: CI runs one test cell with no third-party packages at all, so the
workflow YAML is read with a small indentation parser (jobs -> steps -> run:)
rather than PyYAML.
"""

from __future__ import annotations

import ast
import re
import shlex
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
INVOKE_RE = re.compile(r"python3?\s+((?:eval|scripts)/[\w/.-]+\.py)\b(.*)$")
SHELL_CUT_RE = re.compile(r"\s(?:2>&1|2>|>|\||&&|;)\s?")
JSON_TOKEN_RE = re.compile(r"[\w./-]+\.json\b")


def parse_argparse_contract(source: str) -> dict:
    """Return {'options': set, 'required': set, 'defaults': dict, 'positionals': int}."""
    tree = ast.parse(source)
    options: set[str] = set()
    required: set[str] = set()
    defaults: dict[str, object] = {}
    positionals = 0
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            continue
        names = [
            a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
        ]
        flags = [n for n in names if n.startswith("-")]
        if not flags:
            positionals += 1
            continue
        options.update(flags)
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        req = kw.get("required")
        if isinstance(req, ast.Constant) and req.value is True:
            required.add(flags[-1])
        dflt = kw.get("default")
        if dflt is not None:
            try:
                value = ast.literal_eval(dflt)
            except ValueError:
                # Path("x") and friends: keep the innermost string literal.
                strs = [
                    c.value
                    for c in ast.walk(dflt)
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)
                ]
                value = strs[0] if strs else None
            defaults[flags[-1]] = value
    return {
        "options": options,
        "required": required,
        "defaults": defaults,
        "positionals": positionals,
    }


def _join_continuations(script: str) -> list[str]:
    lines: list[str] = []
    buf = ""
    for raw in script.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        lines.append((buf + line).strip())
        buf = ""
    if buf:
        lines.append(buf.strip())
    return lines


def extract_invocations(run_script: str) -> list[dict]:
    """Find `python <script> <args>` lines; return literal flags and their values."""
    found = []
    for line in _join_continuations(run_script):
        m = INVOKE_RE.search(line)
        if not m or line.lstrip().startswith("#"):
            continue
        script, rest = m.group(1), SHELL_CUT_RE.split(m.group(2), maxsplit=1)[0]
        try:
            tokens = shlex.split(rest)
        except ValueError:
            tokens = rest.split()
        flags: dict[str, str | None] = {}
        dynamic = False
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if tok.startswith("${") or tok.startswith("$@") or tok == "$*":
                dynamic = True  # e.g. "${ARGS[@]}" - contents resolved separately
            elif tok.startswith("--"):
                name, eq, val = tok.partition("=")
                if eq:
                    flags[name] = val
                elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    flags[name] = tokens[i + 1]
                    i += 1
                else:
                    flags[name] = None
            i += 1
        # Flags appended conditionally via bash arrays: ARGS+=(--limit "$LIMIT")
        conditional = set(re.findall(r"\+=\((--[\w-]+)", run_script))
        found.append(
            {
                "script": script,
                "flags": flags,
                "dynamic": dynamic,
                "conditional": conditional,
                "line": line,
            }
        )
    return found


def check_invocation(inv: dict, contract: dict, later_step_text: str) -> list[str]:
    """Pure: violations for one invocation against one argparse contract."""
    problems = []
    for req in sorted(contract["required"]):
        if req not in inv["flags"]:
            where = " (only conditionally appended)" if req in inv["conditional"] else ""
            problems.append(f"missing required flag {req}{where}")
    for flag in sorted(set(inv["flags"]) | inv["conditional"]):
        if flag not in contract["options"]:
            problems.append(f"unknown flag {flag} (script does not define it)")
    if "--out" in contract["options"]:
        effective = inv["flags"].get("--out") or contract["defaults"].get("--out")
        consumed = set(JSON_TOKEN_RE.findall(later_step_text))
        if effective and consumed and effective not in consumed:
            problems.append(
                f"--out resolves to {effective!r} but later steps consume {sorted(consumed)}"
            )
    return problems


def parse_workflow_steps(text: str) -> dict[str, list[dict]]:
    """Dependency-free read of a GitHub workflow: {job: [{'raw': str, 'run': str|None}]}.

    Handles the shapes GitHub Actions files actually use: a `jobs:` mapping,
    two-space job keys, a `steps:` sequence of `- ` items and a `run:` value
    that is either inline or a `|`/`>` block scalar.
    """
    jobs: dict[str, list[dict]] = {}
    job: str | None = None
    in_jobs = False
    step_lines: list[str] | None = None
    step_indent = -1

    def flush() -> None:
        if job is not None and step_lines is not None:
            jobs.setdefault(job, []).append({"raw": "\n".join(step_lines)})

    for line in text.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        if not stripped or stripped.startswith("#"):
            if step_lines is not None:
                step_lines.append(line)
            continue
        if indent == 0:
            flush()
            step_lines, job = None, None
            in_jobs = stripped == "jobs:"
            continue
        if in_jobs and indent == 2 and stripped.endswith(":"):
            flush()
            step_lines, job = None, stripped[:-1].strip("\"'")
            continue
        if job is None:
            continue
        if stripped.startswith("- ") and (step_lines is None or indent <= step_indent):
            flush()
            step_lines, step_indent = [line], indent
            continue
        if step_lines is not None:
            step_lines.append(line)
    flush()

    for steps in jobs.values():
        for step in steps:
            step["run"] = _extract_run(step["raw"])
    return jobs


def _extract_run(raw: str) -> str | None:
    lines = raw.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if not m:
            continue
        key_indent, value = (
            len(m.group(1)) + (2 if m.group(0).lstrip().startswith("- ") else 0),
            m.group(2).strip(),
        )
        if value and value[0] not in "|>":
            return value.strip("\"'")
        block: list[str] = []
        for nxt in lines[i + 1 :]:
            if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) <= key_indent:
                break
            block.append(nxt)
        return textwrap.dedent("\n".join(block))
    return None


def check_workflows(root: Path = ROOT) -> list[dict]:
    """Walk every workflow/job/step; return a list of violation records."""
    violations: list[dict] = []
    contracts: dict[str, dict] = {}
    for wf in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        for job_name, steps in parse_workflow_steps(wf.read_text(encoding="utf-8")).items():
            for idx, step in enumerate(steps):
                run = step["run"]
                if not run:
                    continue
                later = "\n".join(s["raw"] for s in steps[idx + 1 :])
                for inv in extract_invocations(run):
                    path = root / inv["script"]
                    if not path.exists():
                        violations.append(
                            {
                                "workflow": wf.name,
                                "job": job_name,
                                "script": inv["script"],
                                "problems": ["script does not exist in repo"],
                            }
                        )
                        continue
                    if inv["script"] not in contracts:
                        contracts[inv["script"]] = parse_argparse_contract(
                            path.read_text(encoding="utf-8")
                        )
                    problems = check_invocation(inv, contracts[inv["script"]], later)
                    if problems:
                        violations.append(
                            {
                                "workflow": wf.name,
                                "job": job_name,
                                "script": inv["script"],
                                "problems": problems,
                            }
                        )
    return violations


def count_invocations(root: Path = ROOT) -> int:
    return sum(
        len(extract_invocations(step["run"] or ""))
        for wf in (root / ".github" / "workflows").glob("*.y*ml")
        for steps in parse_workflow_steps(wf.read_text(encoding="utf-8")).values()
        for step in steps
    )


def main() -> int:
    violations = check_workflows()
    n_inv = count_invocations()
    for v in violations:
        for p in v["problems"]:
            print(f"VIOLATION {v['workflow']}:{v['job']} -> {v['script']}: {p}")
    print(f"workflow-cli-contract: {n_inv} invocations checked, {len(violations)} violating")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
