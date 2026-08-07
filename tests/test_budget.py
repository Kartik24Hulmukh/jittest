"""Durable accounting and budget unit tests for BudgetManager (Section D)."""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from jittest.budget import BudgetExceededError, BudgetJournalError, BudgetManager


class BudgetManagerTests(unittest.TestCase):
    def test_initial_zero_spend_ceiling(self):
        """USD 0.00 ceiling must reject any billable request immediately."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=0.00, journal_path=Path(tmp_dir) / "j.jsonl"
            )
            with self.assertRaises(BudgetExceededError) as ctx:
                bm.reserve_budget(projected_input_tokens=100, projected_output_tokens=100)
            self.assertIn("Spend ceiling breached", str(ctx.exception))

    def test_atomic_reservation_and_reconciliation(self):
        """Reservation must temporarily hold budget and reconcile with actual usage."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=1.00,
                max_requests=10,
                journal_path=Path(tmp_dir) / "j.jsonl",
            )
            res_id = bm.reserve_budget(
                projected_input_tokens=1000, projected_output_tokens=500
            )

            summary = bm.get_summary()
            self.assertEqual(summary["reserved_requests"], 1)
            self.assertEqual(summary["executed_requests"], 0)

            cost = bm.reconcile_reservation(
                res_id, actual_input_tokens=800, actual_output_tokens=400
            )
            self.assertGreater(cost, 0)

            summary_post = bm.get_summary()
            self.assertEqual(summary_post["reserved_requests"], 0)
            self.assertEqual(summary_post["executed_requests"], 1)

    def test_crash_before_dispatch_recovery(self):
        """Crash before dispatch: persistent journal must replay active reservation on restart."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            j_path = Path(tmp_dir) / "j.jsonl"
            bm1 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
            res_id = bm1.reserve_budget(
                projected_input_tokens=5000, projected_output_tokens=1000
            )

            bm2 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
            self.assertIn(res_id, bm2.active_reservations)
            self.assertEqual(bm2.reserved_input_tokens, 5000)

    def test_crash_immediately_after_dispatch_reconciliation(self):
        """Crash after dispatch: restart allows reconciling preserved active reservation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            j_path = Path(tmp_dir) / "j.jsonl"
            bm1 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
            res_id = bm1.reserve_budget(
                projected_input_tokens=5000, projected_output_tokens=1000
            )

            bm2 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
            cost = bm2.reconcile_reservation(
                res_id, actual_input_tokens=4000, actual_output_tokens=800
            )
            self.assertGreater(cost, 0)

    def test_duplicate_reconciliation_rejected(self):
        """Reconciling same reservation ID twice must raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=1.00, journal_path=Path(tmp_dir) / "j.jsonl"
            )
            res_id = bm.reserve_budget(100, 100)
            bm.reconcile_reservation(res_id, 50, 50)
            with self.assertRaises(ValueError):
                bm.reconcile_reservation(res_id, 50, 50)

    def test_unknown_reservation_id_rejected(self):
        """Unknown reservation ID must raise ValueError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=1.00, journal_path=Path(tmp_dir) / "j.jsonl"
            )
            with self.assertRaises(ValueError):
                bm.reconcile_reservation("unknown-id", 50, 50)

    def test_truncated_final_record_fail_closed(self):
        """Truncated or corrupted journal record must raise BudgetJournalError on restart."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            j_path = Path(tmp_dir) / "corrupt.jsonl"
            j_path.write_text('{"seq": 1, "event": "reserve"\n', encoding="utf-8")
            with self.assertRaises(BudgetJournalError):
                BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)

    def test_journal_write_failure_fail_closed(self):
        """Unwritable journal location must fail closed on reserve attempt."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=1.00, journal_path=Path(tmp_dir) / "j.jsonl"
            )

            def mock_open(*args, **kwargs):
                raise OSError("Disk write I/O error")

            with (
                mock.patch("builtins.open", mock_open),
                self.assertRaises(BudgetJournalError) as ctx,
            ):
                bm.reserve_budget(100, 100)
            self.assertIn("Fail-closed durable journal write failed", str(ctx.exception))

    def test_over_reservation_rejection(self):
        """Request exceeding authorized spend ceiling must raise BudgetExceededError."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=0.001, journal_path=Path(tmp_dir) / "j.jsonl"
            )
            with self.assertRaises(BudgetExceededError):
                bm.reserve_budget(projected_input_tokens=10000, projected_output_tokens=5000)

    def test_actual_usage_over_reservation_enforced(self):
        """Actual usage reconciling higher than reservation is calculated accurately."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=10.00, journal_path=Path(tmp_dir) / "j.jsonl"
            )
            res_id = bm.reserve_budget(100, 100)
            cost = bm.reconcile_reservation(
                res_id, actual_input_tokens=1000, actual_output_tokens=500
            )
            self.assertGreater(cost, 0)

    def test_barrier_based_race_condition_concurrent_dispatch(self):
        """Barrier-based race test proving two concurrent requests cannot pass a one-request ceiling."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            bm = BudgetManager(
                authorized_spend_ceiling_usd=10.00,
                max_requests=1,
                journal_path=Path(tmp_dir) / "j.jsonl",
            )
            barrier = threading.Barrier(2)
            results = []

            def worker():
                barrier.wait()
                try:
                    res_id = bm.reserve_budget(100, 100)
                    results.append(("SUCCESS", res_id))
                except BudgetExceededError as e:
                    results.append(("EXCEEDED", str(e)))

            t1 = threading.Thread(target=worker)
            t2 = threading.Thread(target=worker)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            successes = [r for r in results if r[0] == "SUCCESS"]
            failures = [r for r in results if r[0] == "EXCEEDED"]

            self.assertEqual(len(successes), 1)
            self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
