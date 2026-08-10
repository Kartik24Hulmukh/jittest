"""16-process capacity-1 race overflow tests for requests, input tokens, output tokens, and spend (Mission M3)."""

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from jittest.budget import BudgetExceededError, BudgetManager


def _worker_reserve_req_cap1(journal_path: str, run_id: str, q: multiprocessing.Queue):
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=10.0,
            max_requests=1,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_id = bm.reserve_budget(100, 100)
        q.put(("SUCCESS", res_id))
    except BudgetExceededError as exc:
        q.put(("CEILING_EXCEEDED", str(exc)))
    except Exception as exc:
        q.put(("ERROR", str(exc)))


def _worker_reserve_in_tok_cap1(journal_path: str, run_id: str, q: multiprocessing.Queue):
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=10.0,
            max_input_tokens=100,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_id = bm.reserve_budget(100, 10)
        q.put(("SUCCESS", res_id))
    except BudgetExceededError as exc:
        q.put(("CEILING_EXCEEDED", str(exc)))
    except Exception as exc:
        q.put(("ERROR", str(exc)))


def _worker_reserve_out_tok_cap1(journal_path: str, run_id: str, q: multiprocessing.Queue):
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=10.0,
            max_output_tokens=100,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_id = bm.reserve_budget(10, 100)
        q.put(("SUCCESS", res_id))
    except BudgetExceededError as exc:
        q.put(("CEILING_EXCEEDED", str(exc)))
    except Exception as exc:
        q.put(("ERROR", str(exc)))


def _worker_reserve_spend_cap1(journal_path: str, run_id: str, q: multiprocessing.Queue):
    try:
        bm = BudgetManager(
            authorized_spend_ceiling_usd=0.000150,
            journal_path=journal_path,
            run_id=run_id,
        )
        res_id = bm.reserve_budget(100, 100)
        q.put(("SUCCESS", res_id))
    except BudgetExceededError as exc:
        q.put(("CEILING_EXCEEDED", str(exc)))
    except Exception as exc:
        q.put(("ERROR", str(exc)))


class SixteenProcessAccountingOverflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.j_path = Path(self.tmp_dir.name) / "overflow_journal.jsonl"

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_sixteen_processes_request_capacity_one(self):
        """16 concurrent processes contending for max_requests=1: exactly 1 succeeds, 15 fail."""
        run_id = "test-16p-req"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve_req_cap1, args=(str(self.j_path), run_id, q))
            for _ in range(16)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=15)

        results = []
        while not q.empty():
            results.append(q.get())

        self.assertEqual(len(results), 16)
        successes = [r for r in results if r[0] == "SUCCESS"]
        exceeded = [r for r in results if r[0] == "CEILING_EXCEEDED"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(exceeded), 15, f"Expected exactly 15 ceiling errors, got {results}")

    def test_sixteen_processes_input_token_capacity_one(self):
        """16 concurrent processes contending for max_input_tokens=100: exactly 1 succeeds, 15 fail."""
        run_id = "test-16p-in-tok"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve_in_tok_cap1, args=(str(self.j_path), run_id, q))
            for _ in range(16)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=15)

        results = []
        while not q.empty():
            results.append(q.get())

        self.assertEqual(len(results), 16)
        successes = [r for r in results if r[0] == "SUCCESS"]
        exceeded = [r for r in results if r[0] == "CEILING_EXCEEDED"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(exceeded), 15, f"Expected exactly 15 ceiling errors, got {results}")

    def test_sixteen_processes_output_token_capacity_one(self):
        """16 concurrent processes contending for max_output_tokens=100: exactly 1 succeeds, 15 fail."""
        run_id = "test-16p-out-tok"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve_out_tok_cap1, args=(str(self.j_path), run_id, q))
            for _ in range(16)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=15)

        results = []
        while not q.empty():
            results.append(q.get())

        self.assertEqual(len(results), 16)
        successes = [r for r in results if r[0] == "SUCCESS"]
        exceeded = [r for r in results if r[0] == "CEILING_EXCEEDED"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(exceeded), 15, f"Expected exactly 15 ceiling errors, got {results}")

    def test_sixteen_processes_spend_capacity_one(self):
        """16 concurrent processes contending for spend ceiling: exactly 1 succeeds, 15 fail."""
        run_id = "test-16p-spend"
        q = multiprocessing.Queue()

        workers = [
            multiprocessing.Process(target=_worker_reserve_spend_cap1, args=(str(self.j_path), run_id, q))
            for _ in range(16)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=15)

        results = []
        while not q.empty():
            results.append(q.get())

        self.assertEqual(len(results), 16)
        successes = [r for r in results if r[0] == "SUCCESS"]
        exceeded = [r for r in results if r[0] == "CEILING_EXCEEDED"]

        self.assertEqual(len(successes), 1, f"Expected exactly 1 success, got {results}")
        self.assertEqual(len(exceeded), 15, f"Expected exactly 15 ceiling errors, got {results}")


if __name__ == "__main__":
    unittest.main()
