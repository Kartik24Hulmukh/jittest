"""Offline contract tests for the opt-in live-routing evidence harness."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ga73_live_stress.py"
SPEC = importlib.util.spec_from_file_location("ga73_live_stress_contract", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LiveStressContractTests(unittest.TestCase):
    def test_defaults_match_proven_live_configuration(self):
        args = MODULE.build_parser().parse_args([])
        self.assertEqual(args.deadline, 30.0)
        self.assertEqual(args.max_inflight_per_model, 4)

    def test_override_has_one_dispatch_and_evidence_source(self):
        args = MODULE.build_parser().parse_args(
            ["--deadline", "20", "--max-inflight-per-model", "3"]
        )
        self.assertEqual(
            MODULE.routing_settings(args),
            {"deadline_seconds": 20.0, "max_inflight_per_model": 3},
        )


if __name__ == "__main__":
    unittest.main()
