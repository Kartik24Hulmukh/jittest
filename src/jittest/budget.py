"""Real pre-request budget enforcement and durable accounting module for Jittest evaluation harness (R2A)."""

import hashlib
import json
import os
import threading
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any


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
        self.run_id = run_id or str(uuid.uuid4())

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
        self._lock = threading.Lock()

        if journal_path:
            self.journal_path = Path(journal_path)
        else:
            self.journal_path = Path(f".jittest/journal_{self.run_id}.jsonl")

        self.recover_from_journal()

    def _compute_checksum(self, payload: dict) -> str:
        s = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _append_journal(
        self, entry_type: str, res_id: str, input_tokens: int, output_tokens: int, cost: Decimal
    ) -> None:
        """Durable journal write with fsync (Section D1). Fail-closed on error."""
        self.sequence_number += 1
        record = {
            "run_id": self.run_id,
            "seq": self.sequence_number,
            "event": entry_type,
            "res_id": res_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": str(cost),
        }
        record["checksum"] = self._compute_checksum(
            {k: v for k, v in record.items() if k != "checksum"}
        )

        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as exc:
            raise BudgetJournalError(f"Fail-closed durable journal write failed: {exc}") from exc

    def recover_from_journal(self) -> None:
        """Startup replay/recovery from persistent journal (Section D2-D4). Fail closed on any error."""
        if not self.journal_path.exists():
            return
        try:
            with open(self.journal_path, encoding="utf-8") as f:
                lines = f.readlines()

            expected_seq = 1
            for line in lines:
                if not line.strip():
                    continue
                record = json.loads(line)

                cksum = record.get("checksum")
                computed_ck = self._compute_checksum(
                    {k: v for k, v in record.items() if k != "checksum"}
                )
                if cksum != computed_ck:
                    raise BudgetJournalError(
                        f"Journal recovery failed: checksum mismatch in record {record}"
                    )

                seq = record.get("seq")
                if seq != expected_seq:
                    raise BudgetJournalError(
                        f"Journal recovery failed: sequence out of order (got {seq}, expected {expected_seq})"
                    )
                expected_seq += 1

                evt = record.get("event")
                res_id = record.get("res_id")
                in_tok = int(record.get("input_tokens", 0))
                out_tok = int(record.get("output_tokens", 0))
                cost = Decimal(str(record.get("cost_usd", "0.0")))

                if evt == "reserve":
                    if res_id in self.active_reservations:
                        raise BudgetJournalError(f"Duplicate reservation ID in journal: {res_id}")
                    self.active_reservations[res_id] = {
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cost": cost,
                    }
                    self.reserved_requests += 1
                    self.reserved_input_tokens += in_tok
                    self.reserved_output_tokens += out_tok
                    self.reserved_spend_usd += cost
                elif evt == "reconcile":
                    res = self.active_reservations.pop(res_id, None)
                    if not res:
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

            self.sequence_number = expected_seq - 1

        except Exception as exc:
            if isinstance(exc, BudgetJournalError):
                raise
            raise BudgetJournalError(f"Fail-closed journal recovery failed: {exc}") from exc

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
        """Atomic reservation BEFORE every billable API request / POST attempt (Section C8)."""
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

            # Persist reservation BEFORE changing state (Section D5)
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
            }
            return res_id

    def reconcile_reservation(
        self,
        reservation_id: str,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
        is_unknown_or_partial_failure: bool = False,
    ) -> Decimal:
        """Reconcile atomic reservation with actual provider-reported usage after dispatch."""
        with self._lock:
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

            # Persist incurred liability BEFORE releasing reservation (Section D6)
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
        """Atomic direct usage recording enforcing request, input-token, output-token, and spend ceilings (Section C11)."""
        with self._lock:
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
