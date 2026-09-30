"""Shared instrument screening: generation refusals cannot dilute oracle failures."""
from __future__ import annotations

from eval.ga73_reanalysis import execution_screen


def collection_screen(telemetry: list[dict]) -> dict:
    try:
        screen = execution_screen(telemetry)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return {"healthy_collection": False, "execution_pair_present": False,
                "oracle_entering_candidates": None, "screen": None,
                "problems": [type(exc).__name__]}
    return {"healthy_collection": screen["head_collection_screen"] == "below_20_percent",
            "execution_pair_present": screen["paired_pass_fail_outcomes"] > 0,
            "oracle_entering_candidates": screen["oracle_entering_candidates"],
            "screen": screen, "problems": []}
