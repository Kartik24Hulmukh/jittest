"""Offline contract tests for the opt-in live-routing evidence harness."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ga73_live_stress.py"
SPEC = importlib.util.spec_from_file_location("ga73_live_stress_contract", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class _OfflineRouter:
    received_limit = None

    def __init__(self, *, max_inflight_per_model):
        type(self).received_limit = max_inflight_per_model

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def list_models(self):
        return []


class LiveStressContractTests(unittest.TestCase):
    def test_defaults_match_proven_live_configuration(self):
        args = MODULE.build_parser().parse_args([])
        self.assertEqual(args.deadline, 30.0)
        self.assertEqual(args.max_inflight_per_model, 4)

    def test_override_reaches_router_and_evidence_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence.json"
            argv = [
                str(SCRIPT), "--calls", "4", "--workers", "1",
                "--deadline", "20", "--max-inflight-per-model", "3",
                "--out", str(output),
            ]
            with (
                patch.object(MODULE, "MeliousRouter", _OfflineRouter),
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, {"MELIOUS_API_KEY": "owned-offline-fixture"}),
                patch("builtins.print"),
            ):
                self.assertEqual(MODULE.main(), 1)

            evidence = json.loads(output.read_text())
            self.assertEqual(_OfflineRouter.received_limit, 3)
            self.assertEqual(evidence["deadline_seconds"], 20.0)
            self.assertEqual(evidence["max_inflight_per_model"], 3)
            self.assertEqual(evidence["successful_completions"], 0)


if __name__ == "__main__":
    unittest.main()
