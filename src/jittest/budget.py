"""Real pre-request budget enforcement and durable accounting module for Jittest evaluation harness (R2A)."""

import hashlib
import json
import os
import threading
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

INITIAL_SEAL = "INITIAL_SEAL_GENESIS_CHAIN_HEAD_00010002000300040005000600070008"


class BudgetExceededError(Exception):
    """Raised before dispatching an API request when projected spend or request limits would exceed ceiling."""

    pass


class BudgetJournalError(Exception):
    """Raised when durable journal write or recovery validation fails (fail-closed)."""

    pass


class BudgetManager:
    """Explicit run-scoped pre-request budget guard and durable accounting engine enforcing spend, token, and request limits."""

    def __init__(
        self,
        authorized_spend_ceiling_usd: float = 0.00,
        max_requests: int = 1080,
        max_input_tokens: int = 16200000,
        max_output_tokens: int = 2160000,
        p_rate_usd_per_m: float = 0.30,
        c_rate_usd_per_m: float = 0.90,
        provider_max_tokens: int = 131072,
        journal_path: Path | str | None = None,
        run_id: str | None = None,
    ):
        self.authorized_spend_ceiling_usd = Decimal(str(authorized_spend_ceiling_usd))
        self.max_requests = max_requests
        self.max_input_tokens = max_input_tokens
        self.max_output_tokens = max_output_tokens
        self.p_rate_per_token = Decimal(str(p_rate_usd_per_m)) / Decimal("1000000")
        self.c_rate_per_token = Decimal(str(c_rate_usd_per_m)) / Decimal("1000000")
        self.provider_max_tokens = provider_max_tokens
        self._user_specified_run_id = run_id is not None
        self.run_id = run_id

        self.executed_requests = 0
        self.executed_input_tokens = 0
        self.executed_output_tokens = 0
        self.executed_spend_usd = Decimal("0.00")

        self.reserved_requests = 0
        self.reserved_input_tokens = 0
        self.reserved_output_tokens = 0
        self.reserved_spend_usd = Decimal("0.00")

        self.active_reservations: dict[str, dict[str, Any]] = {}
        self.completed_reservations: set[str] = set()
        self.sequence_number = 0
        self.last_checksum = INITIAL_SEAL
        self._failed_closed = False
        self._lock = threading.Lock()

        if journal_path:
            self.journal_path = Path(journal_path)
        else:
            default_id = self.run_id or str(uuid.uuid4())
            self.journal_path = Path(f".jittest/journal_{default_id}.jsonl")

        self.recover_from_journal()
        if self.run_id is None:
            self.run_id = str(uuid.uuid4())

    def _calculate_cost(self, input_tokens: int, token_rate: Decimal) -> Decimal:
        return Decimal(input_tokens) * token_rate

    def _compute_checksum(self, payload: dict) -> str:
        s = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _acquire_file_lock(self, f):
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            elif os.name == "nt":
                import msvcrt

                pos = f.tell()
                f.seek(0, os.SEEK_SET)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                f.seek(pos, os.SEEK_SET)
        except Exception as exc:
            raise BudgetJournalError(f"File lock acquisition failed: {exc}") from exc

    def _release_file_lock(self, f):
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":
                import msvcrt

                pos = f.tell()
                f.seek(0, os.SEEK_SET)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                f.seek(pos, os.SEEK_SET)
        except Exception:
            pass

    def _with_journal_retry(self, fn):
        for attempt in range(50):
            try:
                return fn()
            except (PermissionError, OSError) as exc:
                if attempt == 49 or getattr(exc, "errno", None) not in (13, 32):
                    raise
                time.sleep(0.05)
        return fn()

    def _append_journal(
        self, entry_type: str, res_id: str, input_tokens: int, output_tokens: int, cost: Decimal
    ) -> None:
        """Durable journal write with fsync (Section D1). Fail-closed on error."""
        if self._failed_closed:
            raise BudgetJournalError("BudgetManager is permanently latched into failed-closed state")

        def _do_write():
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            mode = "a+"
            with open(self.journal_path, mode, encoding="utf-8") as f:
                self._acquire_file_lock(f)
                try:
                    f.seek(0, os.SEEK_SET)
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                    parsed = [json.loads(line) for line in lines]
                    if parsed:
                        last_rec = parsed[-1]
                        self.sequence_number = int(last_rec["seq"])
                        self.last_checksum = str(last_rec["checksum"])

                    if entry_type == "reserve":
                        res_cnt = sum(1 for r in parsed if r.get("event") == "reserve")
                        if (res_cnt + 1) > self.max_requests:
                            raise BudgetExceededError(
                                f"Request ceiling reached: {res_cnt + 1} > {self.max_requests} max requests"
                            )

                    next_seq = self.sequence_number + 1
                    record = {
                        "run_id": self.run_id,
                        "seq": next_seq,
                        "event": entry_type,
                        "res_id": res_id,
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost_usd": str(cost),
                        "prev_checksum": self.last_checksum,
                    }
                    computed_ck = self._compute_checksum(
                        {k: v for k, v in record.items() if k != "checksum"}
                    )
                    record["checksum"] = computed_ck

                    f.seek(0, os.SEEK_END)
                    f.write(json.dumps(record) + "\n")
                    f.flush()
                    os.fsync(f.fileno())

                    self.sequence_number = next_seq
                    self.last_checksum = computed_ck
                finally:
                    self._release_file_lock(f)

        try:
            self._with_journal_retry(_do_write)
        except BudgetExceededError:
            raise
        except Exception as exc:
            self._failed_closed = True
            raise BudgetJournalError(f"Fail-closed durable journal write failed: {exc}") from exc

    def recover_from_journal(self) -> None:
        """Startup replay/recovery from persistent journal. Fail closed on any error."""
        if not self.journal_path.exists():
            return

        def _do_read():
            with open(self.journal_path, encoding="utf-8") as f:
                self._acquire_file_lock(f)
                try:
                    return f.readlines()
                finally:
                    self._release_file_lock(f)

        try:
            lines = self._with_journal_retry(_do_read)

            expected_seq = 1
            expected_prev_checksum = INITIAL_SEAL
            for line in lines:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except Exception as e:
                    self._failed_closed = True
                    raise BudgetJournalError(f"Malformed JSON in journal record: {line}") from e

                cksum = record.get("checksum")
                computed_ck = self._compute_checksum(
                    {k: v for k, v in record.items() if k != "checksum"}
                )
                if cksum != computed_ck:
                    self._failed_closed = True
                    raise BudgetJournalError(
                        f"Journal recovery failed: checksum mismatch in record {record}"
                    )

                prev_ck = record.get("prev_checksum")
                if prev_ck != expected_prev_checksum:
                    self._failed_closed = True
                    raise BudgetJournalError(
                        f"Journal recovery failed: checksum chain broken (got {prev_ck}, expected {expected_prev_checksum})"
                    )

                seq = record.get("seq")
                if seq != expected_seq:
                    self._failed_closed = True
                    raise BudgetJournalError(
                        f"Journal recovery failed: sequence out of order (got {seq}, expected {expected_seq})"
                    )

                rec_run_id = record.get("run_id")
                if self.run_id is None or not self._user_specified_run_id:
                    self.run_id = rec_run_id
                    self._user_specified_run_id = True
                elif rec_run_id != self.run_id:
                    self._failed_closed = True
                    raise BudgetJournalError(
                        f"Journal recovery failed: mixed run IDs (got {rec_run_id}, expected {self.run_id})"
                    )

                evt = record.get("event")
                if evt not in ("reserve", "dispatch_start", "reconcile", "seal"):
                    self._failed_closed = True
                    raise BudgetJournalError(f"Journal recovery failed: unknown event type '{evt}'")

                res_id = record.get("res_id")
                try:
                    in_tok = int(record.get("input_tokens", 0))
                    out_tok = int(record.get("output_tokens", 0))
                    cost = Decimal(str(record.get("cost_usd", "0.0")))
                except (ValueError, InvalidOperation) as e:
                    self._failed_closed = True
                    raise BudgetJournalError(f"Journal recovery failed: malformed numbers in {record}") from e

                if in_tok < 0 or out_tok < 0 or cost < Decimal("0.0"):
                    self._failed_closed = True
                    raise BudgetJournalError(f"Journal recovery failed: negative values in {record}")

                expected_cost = self.calculate_cost(in_tok, out_tok)
                if abs(cost - expected_cost) > Decimal("0.000001"):
                    self._failed_closed = True
                    raise BudgetJournalError(
                        f"Journal recovery failed: inconsistent cost in {record} (got {cost}, expected {expected_cost})"
                    )

                if evt == "reserve":
                    if res_id in self.active_reservations:
                        self._failed_closed = True
                        raise BudgetJournalError(f"Duplicate reservation ID in journal: {res_id}")
                    self.active_reservations[res_id] = {
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cost": cost,
                        "dispatched": False,
                    }
                    self.reserved_requests += 1
                    self.reserved_input_tokens += in_tok
                    self.reserved_output_tokens += out_tok
                    self.reserved_spend_usd += cost
                elif evt == "dispatch_start":
                    if res_id in self.active_reservations:
                        self.active_reservations[res_id]["dispatched"] = True
                elif evt == "reconcile":
                    res = self.active_reservations.pop(res_id, None)
                    if not res:
                        self._failed_closed = True
                        raise BudgetJournalError(
                            f"Reconciling unknown reservation ID in journal: {res_id}"
                        )
                    self.completed_reservations.add(res_id)

                    self.reserved_requests -= 1
                    self.reserved_input_tokens -= res["input_tokens"]
                    self.reserved_output_tokens -= res["output_tokens"]
                    self.reserved_spend_usd -= res["cost"]

                    self.executed_requests += 1
                    self.executed_input_tokens += in_tok
                    self.executed_output_tokens += out_tok
                    self.executed_spend_usd += cost

                expected_seq += 1
                expected_prev_checksum = computed_ck

            self.sequence_number = expected_seq - 1
            self.last_checksum = expected_prev_checksum

            seal_path = self.journal_path.with_suffix(".seal")
            if seal_path.exists():
                try:
                    seal = json.loads(seal_path.read_text(encoding="utf-8"))
                    tot_rec = int(seal.get("total_records", 0))
                    head_ck = str(seal.get("head_checksum", ""))
                    if (expected_seq - 1) < tot_rec or expected_prev_checksum != head_ck:
                        self._failed_closed = True
                        raise BudgetJournalError(
                            f"Journal recovery failed: complete tail deletion detected (recovered {expected_seq - 1} records, expected {tot_rec})"
                        )
                except Exception as e:
                    if isinstance(e, BudgetJournalError):
                        raise
                    self._failed_closed = True
                    raise BudgetJournalError(f"Journal seal verification failed: {e}") from e

        except Exception as exc:
            self._failed_closed = True
            if isinstance(exc, BudgetJournalError):
                raise
            raise BudgetJournalError(f"Fail-closed journal recovery failed: {exc}") from exc

    def write_seal(self) -> None:
        """Write durable sidecar seal committing total records and head checksum for tail deletion detection."""
        seal_path = self.journal_path.with_suffix(".seal")
        seal_data = {
            "run_id": self.run_id,
            "total_records": self.sequence_number,
            "head_checksum": self.last_checksum,
        }
        seal_path.write_text(json.dumps(seal_data), encoding="utf-8")

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Calculate exact USD cost for given token counts. Rejects negative tokens."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(
                f"Negative token counts rejected: in={input_tokens}, out={output_tokens}"
            )
        in_cost = Decimal(input_tokens) * self.p_rate_per_token
        out_cost = Decimal(output_tokens) * self.c_rate_per_token
        return in_cost + out_cost

    def reserve_budget(
        self,
        projected_input_tokens: int = 15000,
        projected_output_tokens: int = 2000,
        max_tokens_override: int | None = None,
    ) -> str:
        """Atomic reservation BEFORE every billable API request / POST attempt."""
        if self._failed_closed:
            raise BudgetJournalError("BudgetManager is permanently latched into failed-closed state")

        if projected_input_tokens < 0 or projected_output_tokens < 0:
            raise ValueError(
                f"Negative token projections rejected: in={projected_input_tokens}, out={projected_output_tokens}"
            )

        max_tok = min(
            self.provider_max_tokens,
            max_tokens_override if max_tokens_override is not None else self.provider_max_tokens,
        )

        if (
            projected_output_tokens > max_tok
            or (projected_input_tokens + projected_output_tokens) > max_tok
        ):
            raise BudgetExceededError(
                f"Provider max_tokens limit exceeded: projected tokens ({projected_input_tokens} in + {projected_output_tokens} out) exceed max {max_tok}"
            )

        with self._lock:
            total_requests = self.executed_requests + self.reserved_requests + 1
            if total_requests > self.max_requests:
                raise BudgetExceededError(
                    f"Request ceiling reached: {total_requests} > {self.max_requests} max requests"
                )

            total_in = (
                self.executed_input_tokens + self.reserved_input_tokens + projected_input_tokens
            )
            if total_in > self.max_input_tokens:
                raise BudgetExceededError(
                    f"Input token ceiling reached: {total_in} > {self.max_input_tokens}"
                )

            total_out = (
                self.executed_output_tokens + self.reserved_output_tokens + projected_output_tokens
            )
            if total_out > self.max_output_tokens:
                raise BudgetExceededError(
                    f"Output token ceiling reached: {total_out} > {self.max_output_tokens}"
                )

            projected_cost = self.calculate_cost(projected_input_tokens, projected_output_tokens)
            total_spend = self.executed_spend_usd + self.reserved_spend_usd + projected_cost
            if total_spend > self.authorized_spend_ceiling_usd:
                raise BudgetExceededError(
                    f"Spend ceiling breached: total spend ${total_spend:.6f} USD > authorized ${self.authorized_spend_ceiling_usd:.6f} USD ceiling"
                )

            res_id = str(uuid.uuid4())

            # Persist reservation BEFORE changing state
            self._append_journal(
                "reserve", res_id, projected_input_tokens, projected_output_tokens, projected_cost
            )

            self.reserved_requests += 1
            self.reserved_input_tokens += projected_input_tokens
            self.reserved_output_tokens += projected_output_tokens
            self.reserved_spend_usd += projected_cost

            self.active_reservations[res_id] = {
                "input_tokens": projected_input_tokens,
                "output_tokens": projected_output_tokens,
                "cost": projected_cost,
                "dispatched": False,
            }
            return res_id

    def record_dispatch_start(self, reservation_id: str) -> None:
        """Persist dispatch-start event before network call."""
        with self._lock:
            if self._failed_closed:
                raise BudgetJournalError("BudgetManager is permanently latched into failed-closed state")
            res = self.active_reservations.get(reservation_id)
            if not res:
                raise ValueError(f"Unknown reservation ID {reservation_id}")
            self._append_journal("dispatch_start", reservation_id, res["input_tokens"], res["output_tokens"], res["cost"])
            res["dispatched"] = True

    def reconcile_reservation(
        self,
        reservation_id: str,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
        is_unknown_or_partial_failure: bool = False,
    ) -> Decimal:
        """Reconcile atomic reservation with actual provider-reported usage after dispatch."""
        with self._lock:
            if self._failed_closed:
                raise BudgetJournalError("BudgetManager is permanently latched into failed-closed state")

            if reservation_id in self.completed_reservations:
                raise ValueError(f"Reservation ID {reservation_id} has already been reconciled!")

            res = self.active_reservations.get(reservation_id)
            if not res:
                raise ValueError(f"Unknown reservation ID {reservation_id}")

            if (
                is_unknown_or_partial_failure
                or actual_input_tokens is None
                or actual_output_tokens is None
            ):
                final_in = res["input_tokens"]
                final_out = res["output_tokens"]
            else:
                if actual_input_tokens < 0 or actual_output_tokens < 0:
                    raise ValueError(
                        f"Negative actual tokens rejected: in={actual_input_tokens}, out={actual_output_tokens}"
                    )
                final_in = actual_input_tokens
                final_out = actual_output_tokens

            cost = self.calculate_cost(final_in, final_out)

            # Check if actual cost/usage breaches ceilings
            exec_spend = self.executed_spend_usd + cost
            if exec_spend > self.authorized_spend_ceiling_usd:
                # Persist full liability, latch future dispatch closed, surface budget overage
                self._append_journal("reconcile", reservation_id, final_in, final_out, cost)
                self._failed_closed = True
                raise BudgetExceededError(f"Actual usage cost ${cost:.6f} breached authorized ceiling ${self.authorized_spend_ceiling_usd:.6f}")

            # Persist incurred liability BEFORE releasing reservation
            self._append_journal("reconcile", reservation_id, final_in, final_out, cost)

            self.active_reservations.pop(reservation_id)
            self.completed_reservations.add(reservation_id)

            self.reserved_requests -= 1
            self.reserved_input_tokens -= res["input_tokens"]
            self.reserved_output_tokens -= res["output_tokens"]
            self.reserved_spend_usd -= res["cost"]

            self.executed_requests += 1
            self.executed_input_tokens += final_in
            self.executed_output_tokens += final_out
            self.executed_spend_usd += cost

            return cost

    def record_usage(self, input_tokens: int, output_tokens: int) -> Decimal:
        """Atomic direct usage recording enforcing request, input-token, output-token, and spend ceilings."""
        with self._lock:
            if self._failed_closed:
                raise BudgetJournalError("BudgetManager is permanently latched into failed-closed state")

            if input_tokens < 0 or output_tokens < 0:
                raise ValueError("Negative tokens rejected")

            if (self.executed_requests + self.reserved_requests + 1) > self.max_requests:
                raise BudgetExceededError("Request ceiling reached in record_usage")

            if (
                self.executed_input_tokens + self.reserved_input_tokens + input_tokens
            ) > self.max_input_tokens:
                raise BudgetExceededError("Input token ceiling reached in record_usage")

            if (
                self.executed_output_tokens + self.reserved_output_tokens + output_tokens
            ) > self.max_output_tokens:
                raise BudgetExceededError("Output token ceiling reached in record_usage")

            cost = self.calculate_cost(input_tokens, output_tokens)
            if (
                self.executed_spend_usd + self.reserved_spend_usd + cost
            ) > self.authorized_spend_ceiling_usd:
                raise BudgetExceededError("Spend ceiling reached in record_usage")

            res_id = str(uuid.uuid4())
            self._append_journal("reserve", res_id, input_tokens, output_tokens, cost)
            self._append_journal("reconcile", res_id, input_tokens, output_tokens, cost)

            self.executed_requests += 1
            self.executed_input_tokens += input_tokens
            self.executed_output_tokens += output_tokens
            self.executed_spend_usd += cost
            self.completed_reservations.add(res_id)
            return cost

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_id": self.run_id,
                "authorized_spend_ceiling_usd": float(self.authorized_spend_ceiling_usd),
                "executed_spend_usd": float(self.executed_spend_usd),
                "reserved_spend_usd": float(self.reserved_spend_usd),
                "executed_requests": self.executed_requests,
                "reserved_requests": self.reserved_requests,
                "max_requests": self.max_requests,
                "executed_input_tokens": self.executed_input_tokens,
                "executed_output_tokens": self.executed_output_tokens,
                "remaining_spend_usd": float(
                    max(
                        Decimal("0.00"),
                        self.authorized_spend_ceiling_usd
                        - self.executed_spend_usd
                        - self.reserved_spend_usd,
                    )
                ),
            }
