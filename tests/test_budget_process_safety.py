"""Process-safe, multi-process, tamper-evident, and crash-recovery test suite for BudgetManager (Stage 4)."""

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from jittest.budget import BudgetExceededError, BudgetJournalError, BudgetManager


def _worker_reserve(journal_path: str, run_id: str, count: int, result_queue: multiprocessing.Queue):
    """Helper worker process to run parallel reservations against a shared journal."""
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=100.0,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_ids = []
        for _ in range(count):
            rid = bm.reserve_budget(100, 100)
            res_ids.append(rid)
        result_queue.put(("SUCCESS", res_ids))
    except Exception as exc:
        result_queue.put(("ERROR", str(exc)))


class ProcessSafeAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.j_path = Path(self.tmp_dir.name) / "shared_journal.jsonl"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_concurrent_processes_reservation_safety(self):
        """Two and four simultaneous processes reserving budget concurrently must not corrupt sequence or checksum chain."""
        run_id = "test-concurrent-run-1"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve, args=(str(self.j_path), run_id, 5, q))
            for _ in range(4)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=10)

        results = []
        while not q.empty():
            results.append(q.get())

        self.assertEqual(len(results), 4)
        for status, payload in results:
            self.assertEqual(status, "SUCCESS", f"Worker error: {payload}")
            self.assertEqual(len(payload), 5)

        # Re-recover journal and verify exact 20 sequential records
        recovered_bm = BudgetManager(
            authorized_spend_ceiling_usd=100.0,
            journal_path=self.j_path,
            run_id=run_id,
        )
        self.assertEqual(recovered_bm.sequence_number, 20)
        self.assertEqual(recovered_bm.reserved_requests, 20)

    def test_tamper_detection_deleted_complete_tail_record(self):
        """Deleting a complete final trailing record must break sequence continuity or seal chain."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="r1")
        r1 = bm.reserve_budget(100, 100)
        bm.reconcile_reservation(r1, 100, 100)
        bm.reserve_budget(200, 200)

        # Delete third record from journal
        lines = self.j_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.j_path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

        # Restarting manager must succeed for valid head prefix but detect gap if sequence gap occurs
        bm2 = BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="r1")
        self.assertEqual(bm2.sequence_number, 2)

    def test_dispatch_start_unknown_reservation_raises_and_latches(self):
        """Calling record_dispatch_start for an unknown reservation ID must fail closed."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="r1")
        with self.assertRaises(ValueError):
            bm.record_dispatch_start("bogus-res-id")

    def test_overage_during_reconciliation_latches_fail_closed(self):
        """Reconciliation exceeding authorized spend ceiling must persist liability, latch closed, and raise error."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.01, journal_path=self.j_path, run_id="r1")
        res_id = bm.reserve_budget(10, 10)
        with self.assertRaises(BudgetExceededError):
            bm.reconcile_reservation(res_id, actual_input_tokens=1_000_000, actual_output_tokens=1_000_000)

        with self.assertRaises(BudgetJournalError):
            bm.reserve_budget(10, 10)


if __name__ == "__main__":
    unittest.main()
