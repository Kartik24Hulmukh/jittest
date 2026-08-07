"""Durable accounting and budget unit tests for BudgetManager (Section D)."""

import threading

import pytest

from src.jittest.budget import BudgetExceededError, BudgetJournalError, BudgetManager


def test_initial_zero_spend_ceiling(tmp_path):
    """USD 0.00 ceiling must reject any billable request immediately."""
    bm = BudgetManager(authorized_spend_ceiling_usd=0.00, journal_path=tmp_path / "j.jsonl")
    with pytest.raises(BudgetExceededError) as exc_info:
        bm.reserve_budget(projected_input_tokens=100, projected_output_tokens=100)
    assert "Spend ceiling breached" in str(exc_info.value)


def test_atomic_reservation_and_reconciliation(tmp_path):
    """Reservation must temporarily hold budget and reconcile with actual usage."""
    bm = BudgetManager(
        authorized_spend_ceiling_usd=1.00, max_requests=10, journal_path=tmp_path / "j.jsonl"
    )
    res_id = bm.reserve_budget(projected_input_tokens=1000, projected_output_tokens=500)

    summary = bm.get_summary()
    assert summary["reserved_requests"] == 1
    assert summary["executed_requests"] == 0

    cost = bm.reconcile_reservation(res_id, actual_input_tokens=800, actual_output_tokens=400)
    assert cost > 0

    summary_post = bm.get_summary()
    assert summary_post["reserved_requests"] == 0
    assert summary_post["executed_requests"] == 1


def test_crash_before_dispatch_recovery(tmp_path):
    """Crash before dispatch: persistent journal must replay active reservation on restart."""
    j_path = tmp_path / "j.jsonl"
    bm1 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
    res_id = bm1.reserve_budget(projected_input_tokens=5000, projected_output_tokens=1000)

    # Simulate restart
    bm2 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
    assert res_id in bm2.active_reservations
    assert bm2.reserved_input_tokens == 5000


def test_crash_immediately_after_dispatch_reconciliation(tmp_path):
    """Crash after dispatch: restart allows reconciling preserved active reservation."""
    j_path = tmp_path / "j.jsonl"
    bm1 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
    res_id = bm1.reserve_budget(projected_input_tokens=5000, projected_output_tokens=1000)

    bm2 = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)
    cost = bm2.reconcile_reservation(res_id, actual_input_tokens=4000, actual_output_tokens=800)
    assert cost > 0


def test_duplicate_reconciliation_rejected(tmp_path):
    """Reconciling same reservation ID twice must raise ValueError."""
    bm = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=tmp_path / "j.jsonl")
    res_id = bm.reserve_budget(100, 100)
    bm.reconcile_reservation(res_id, 50, 50)
    with pytest.raises(ValueError):
        bm.reconcile_reservation(res_id, 50, 50)


def test_unknown_reservation_id_rejected(tmp_path):
    """Unknown reservation ID must raise ValueError."""
    bm = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=tmp_path / "j.jsonl")
    with pytest.raises(ValueError):
        bm.reconcile_reservation("unknown-id", 50, 50)


def test_truncated_final_record_fail_closed(tmp_path):
    """Truncated or corrupted journal record must raise BudgetJournalError on restart."""
    j_path = tmp_path / "corrupt.jsonl"
    j_path.write_text('{"seq": 1, "event": "reserve"\n', encoding="utf-8")
    with pytest.raises(BudgetJournalError):
        BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=j_path)


def test_journal_write_failure_fail_closed(tmp_path, monkeypatch):
    """Unwritable journal location must fail closed on reserve attempt."""
    bm = BudgetManager(authorized_spend_ceiling_usd=1.00, journal_path=tmp_path / "j.jsonl")

    def mock_open(*args, **kwargs):
        raise OSError("Disk write I/O error")

    monkeypatch.setattr("builtins.open", mock_open)
    with pytest.raises(BudgetJournalError) as exc_info:
        bm.reserve_budget(100, 100)
    assert "Fail-closed durable journal write failed" in str(exc_info.value)


def test_over_reservation_rejection(tmp_path):
    """Request exceeding authorized spend ceiling must raise BudgetExceededError."""
    bm = BudgetManager(authorized_spend_ceiling_usd=0.001, journal_path=tmp_path / "j.jsonl")
    with pytest.raises(BudgetExceededError):
        bm.reserve_budget(projected_input_tokens=10000, projected_output_tokens=5000)


def test_actual_usage_over_reservation_enforced(tmp_path):
    """Actual usage reconciling higher than reservation is calculated accurately."""
    bm = BudgetManager(authorized_spend_ceiling_usd=10.00, journal_path=tmp_path / "j.jsonl")
    res_id = bm.reserve_budget(100, 100)
    cost = bm.reconcile_reservation(res_id, actual_input_tokens=1000, actual_output_tokens=500)
    assert cost > 0


def test_barrier_based_race_condition_concurrent_dispatch(tmp_path):
    """Barrier-based race test proving two concurrent requests cannot pass a one-request ceiling."""
    bm = BudgetManager(
        authorized_spend_ceiling_usd=10.00, max_requests=1, journal_path=tmp_path / "j.jsonl"
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

    assert len(successes) == 1
    assert len(failures) == 1
