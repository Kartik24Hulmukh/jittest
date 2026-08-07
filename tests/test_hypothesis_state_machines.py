"""Hypothesis RuleBasedStateMachine property tests for BudgetManager state transitions (Stage 7)."""

import contextlib
import tempfile
import unittest
from pathlib import Path

try:
    from hypothesis import strategies as st
    from hypothesis.stateful import Bundle, RuleBasedStateMachine, rule, run_state_machine_as_test
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

from jittest.budget import BudgetExceededError, BudgetManager

if HAS_HYPOTHESIS:

    class BudgetManagerStateMachine(RuleBasedStateMachine):
        def __init__(self):
            super().__init__()
            self.tmp_dir = tempfile.TemporaryDirectory()
            self.journal_path = Path(self.tmp_dir.name) / "state_machine_journal.jsonl"
            self.bm = BudgetManager(
                authorized_spend_ceiling_usd=10.0,
                max_requests=100,
                journal_path=self.journal_path,
                run_id="sm-run-1",
            )
            self.active_reservations = []

        reservations = Bundle("reservations")

        @rule(
            target=reservations,
            in_tok=st.integers(min_value=1, max_value=1000),
            out_tok=st.integers(min_value=1, max_value=1000),
        )
        def reserve(self, in_tok, out_tok):
            try:
                res_id = self.bm.reserve_budget(in_tok, out_tok)
                self.active_reservations.append(res_id)
                return res_id
            except BudgetExceededError:
                return None

        @rule(res_id=reservations)
        def dispatch_start(self, res_id):
            if res_id and res_id in self.active_reservations:
                with contextlib.suppress(ValueError):
                    self.bm.record_dispatch_start(res_id)

        @rule(res_id=reservations)
        def reconcile(self, res_id):
            if res_id and res_id in self.active_reservations:
                try:
                    self.bm.reconcile_reservation(res_id, 50, 50)
                    self.active_reservations.remove(res_id)
                except (ValueError, BudgetExceededError):
                    pass

        def teardown(self):
            self.tmp_dir.cleanup()

    # Expose the state machine as a real TestCase so Hypothesis auto-generates test sequences
    TestBudgetManagerStateMachine = BudgetManagerStateMachine.TestCase


class HypothesisStateMachineTests(unittest.TestCase):
    def test_state_machine_execution(self):
        """Execute Hypothesis state machine runner for automated sequence generation."""
        if not HAS_HYPOTHESIS:
            self.skipTest("hypothesis package not installed")
        run_state_machine_as_test(BudgetManagerStateMachine)


if __name__ == "__main__":
    unittest.main()
