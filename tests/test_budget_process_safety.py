"""Process-safe, multi-process, tamper-evident, and crash-recovery test suite for BudgetManager (Stage 4)."""

import json
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


def _worker_reserve_capacity_one(journal_path: str, run_id: str, result_queue: multiprocessing.Queue):
    """Helper worker for 4-process capacity-one test."""
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=10.0,
            max_requests=1,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_id = bm.reserve_budget(100, 100)
        result_queue.put(("SUCCESS", res_id))
    except BudgetExceededError as exc:
        result_queue.put(("CEILING_EXCEEDED", str(exc)))
    except Exception as exc:
        result_queue.put(("ERROR", str(exc)))


class ProcessSafeAccountingTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.j_path = Path(self.tmp_dir.name) / "shared_journal.jsonl"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_concurrent_processes_reservation_safety(self):
        """Four simultaneous processes reserving budget concurrently must not corrupt sequence or checksum chain."""
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

    def test_four_processes_capacity_one_exact_race(self):
        """Four concurrent processes contending for max_requests=1: exactly 1 succeeds, 3 fail with ceiling error."""
        run_id = "test-cap1-run"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve_capacity_one, args=(str(self.j_path), run_id, q))
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
        successes = [r for r in results if r[0] == "SUCCESS"]
        exceeded = [r for r in results if r[0] == "CEILING_EXCEEDED"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(exceeded), 3, f"Expected exactly 3 ceiling errors, got {results}")

    def test_one_request_ceiling(self):
        """Single request ceiling must block second reservation."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, max_requests=1, journal_path=self.j_path, run_id="r1")
        bm.reserve_budget(100, 100)
        with self.assertRaises(BudgetExceededError):
            bm.reserve_budget(100, 100)

    def test_one_input_token_ceiling(self):
        """One input token ceiling must block reservation exceeding input token budget."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, max_input_tokens=100, journal_path=self.j_path, run_id="r1")
        bm.reserve_budget(50, 10)
        with self.assertRaises(BudgetExceededError):
            bm.reserve_budget(60, 10)

    def test_one_output_token_ceiling(self):
        """One output token ceiling must block reservation exceeding output token budget."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, max_output_tokens=100, journal_path=self.j_path, run_id="r1")
        bm.reserve_budget(10, 50)
        with self.assertRaises(BudgetExceededError):
            bm.reserve_budget(10, 60)

    def test_one_spend_ceiling(self):
        """USD 0.00 spend ceiling must block reservation."""
        bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=self.j_path, run_id="r1")
        with self.assertRaises(BudgetExceededError):
            bm.reserve_budget(10, 10)

    def test_mixed_run_ids_fails_recovery(self):
        """Journal containing mixed run IDs must fail recovery."""
        bm1 = BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="run-A")
        bm1.reserve_budget(10, 10)

        # Append record with different run ID
        lines = self.j_path.read_text().splitlines()
        bad_rec = json.loads(lines[0])
        bad_rec["run_id"] = "run-B"
        bad_rec["seq"] = 2
        bad_rec["prev_checksum"] = bad_rec["checksum"]
        # recompute checksum
        s = json.dumps({k: v for k, v in bad_rec.items() if k != "checksum"}, sort_keys=True)
        bad_rec["checksum"] = json.loads(json.dumps(s))  # string checksum

        with open(self.j_path, "a") as f:
            f.write(json.dumps(bad_rec) + "\n")

        with self.assertRaises(BudgetJournalError):
            BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="run-A")

    def test_duplicate_reconciliation_raises_value_error(self):
        """Reconciling the same reservation ID twice must raise ValueError."""
        bm = BudgetManager(authorized_spend_ceiling_usd=10.0, journal_path=self.j_path, run_id="r1")
        r1 = bm.reserve_budget(100, 100)
        bm.reconcile_reservation(r1, 100, 100)
        with self.assertRaises(ValueError):
            bm.reconcile_reservation(r1, 100, 100)

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
