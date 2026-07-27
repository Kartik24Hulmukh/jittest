"""Refuse to let an evaluation run finish green without measuring anything.

Two benchmark runs in this project completed in 37 and 32 seconds, reported
`success`, and measured nothing at all. Both were counted as progress for a day.
The workflow itself must therefore be unable to pass in that state.

Defect 30: the first version of this gate trusted the shape of its own input.
A `summary` that was a string raised AttributeError, and negative counts
(`bugs_measured: -2`) passed straight through `int(... or 0)` and were treated
as a measured run. A gate that can crash, or that can be satisfied by
impossible numbers, is not a gate. Every value is now range-checked, and any
unreadable structure fails closed.

Exit codes:
  0  at least one model request was issued and results are present
  1  the results file is missing, malformed, or describes a run that measured
     nothing

Usage:
  python eval/assert_measured.py results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _count(summary: dict, key: str, problems: list[str]) -> int:
    """Read a non-negative integer count, failing closed on anything else.

    Returns 0 for anything unusable, and records why. Returning 0 is the safe
    direction: 0 always fails the gate below.
    """
    raw = summary.get(key)
    if raw is None:
        problems.append(f"summary.{key} is missing")
        return 0
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        problems.append(
            f"summary.{key} is {type(raw).__name__} ({raw!r}), not a number")
        return 0
    if raw != raw or raw in (float("inf"), float("-inf")):  # NaN / infinity
        problems.append(f"summary.{key} is not a finite number ({raw!r})")
        return 0
    value = int(raw)
    if value < 0:
        problems.append(
            f"summary.{key} is negative ({value}), which is impossible; "
            "the harness reported a corrupt count")
        return 0
    return value


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "results.json")
    if not path.exists():
        print(f"FAIL: {path} does not exist. The harness did not produce results.",
              file=sys.stderr)
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"FAIL: {path} is not readable JSON: {exc}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print(f"FAIL: {path} does not contain a JSON object at the top level "
              f"(found {type(payload).__name__}).", file=sys.stderr)
        return 1

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        print(f"FAIL: summary is {type(summary).__name__}, not an object. "
              "The harness did not write a usable summary, so nothing can be "
              "claimed about this run.", file=sys.stderr)
        return 1

    results = payload.get("results")
    if not isinstance(results, list):
        results = []

    print(json.dumps(summary, indent=2, default=str))

    problems: list[str] = []
    requests = _count(summary, "model_requests_total", problems)
    measured = _count(summary, "bugs_measured", problems)
    attempted = _count(summary, "bugs_attempted", problems)

    if attempted == 0:
        problems.append("no bugs were attempted: check the BugsInPy clone and --limit")
    if requests == 0:
        problems.append(
            "no model request was issued, so nothing was measured. Common causes: "
            "an empty diff for every revision pair, JITTEST_API_KEY absent from "
            "the job environment, or every target filtered below the risk threshold")
    if measured == 0:
        problems.append("bugs_measured is 0: there is no catch rate to report")
    if measured > attempted > 0:
        problems.append(
            f"bugs_measured ({measured}) exceeds bugs_attempted ({attempted})")

    catch_rate = summary.get("catch_rate")
    if isinstance(catch_rate, (int, float)) and not isinstance(catch_rate, bool):
        if catch_rate == 0.0 and measured == 0:
            problems.append(
                "catch_rate 0.0 was reported for a run that measured nothing")
        elif not 0.0 <= float(catch_rate) <= 1.0:
            problems.append(f"catch_rate {catch_rate!r} is outside 0.0-1.0")

    empty_reasons = {
        r.get("error", "") for r in results
        if isinstance(r, dict) and r.get("status") == "not_measured" and r.get("error")
    }
    for reason in sorted(empty_reasons):
        print(f"  not_measured reason: {reason}", file=sys.stderr)

    if problems:
        print("", file=sys.stderr)
        print("THIS RUN MEASURED NOTHING. Failing on purpose.", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"OK: {measured}/{attempted} bugs measured across {requests} model requests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
