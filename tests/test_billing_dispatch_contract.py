"""Specification fixtures over real localhost HTTP; no paid provider or corpus code."""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from jittest._billing import summarize_dispatch_ledger
from jittest.llm import (
    HTTPLLM,
    BudgetExceeded,
    LLMError,
    ModelUnavailableError,
    QuotaExhaustedError,
    TimedOutError,
)

BILL = {"credits": "0.0000031", "paid_with": "credits"}
GOOD = {"choices": [{"message": {"content": "OK"}}],
        "usage": {"prompt_tokens": 19, "completion_tokens": 3}, "billing_cost": BILL}


@contextlib.contextmanager
def provider(responses):
    """Owned HTTP specification server, not a substituted client/transport."""
    queue = list(responses)
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen.append(True)
            status, body, headers, delay = queue.pop(0)
            if delay:
                time.sleep(delay)
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            try:
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except OSError:
                pass  # the timeout fixture intentionally closes its own socket

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with patch.dict(os.environ, {"JITTEST_API_BASE": f"http://127.0.0.1:{server.server_port}/v1",
                                     "JITTEST_MODEL_PRICE": "1,3"}):
            yield seen
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def response(body=GOOD, status=200, request_id="request-1", delay=0):
    return status, body, {"X-Request-ID": request_id}, delay


class BillingDispatchContract(unittest.TestCase):
    def client(self, events=None, **kwargs):
        llm = HTTPLLM("melious/glm-5.3-flash", api_key="owned-fixture-key", **kwargs,
                      dispatch_ledger=events)
        llm.max_attempts = 2
        llm.max_sleep = 0
        return llm

    def test_baseline_loses_billing_on_malformed_content(self):
        body = dict(GOOD, choices="broken")
        with provider([response(body)]):
            llm = HTTPLLM("melious/glm-5.3-flash", api_key="owned-fixture-key")
            with self.assertRaises(LLMError):
                llm.complete("private prompt", "private context")
        self.assertEqual(llm.usage.provider_billing["provider_credit_debit_eur"], "0.0000031")
        self.assertEqual(llm.usage.calls, 0)  # do not silently redefine response/token counters

    def test_malformed_usage_retains_billing_and_parsed_content(self):
        events = []
        with provider([response(dict(GOOD, usage="broken"))]):
            llm = self.client(events)
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertEqual(llm.usage.provider_billing["provider_response_count"], 1)
        self.assertEqual(events[0]["content_parse_status"], "parsed")
        self.assertEqual(events[0]["usage_parse_status"], "failed")

    def test_success_exact_billing_actual_request_id_and_missing_context(self):
        events = []
        with provider([response()]) as seen:
            llm = self.client(events)
            self.assertEqual(llm.complete("secret prompt", "secret user"), ["OK"])
        self.assertEqual(len(seen), 1)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["event_type"], "dispatch")
        self.assertEqual(event["provider_request_id"], "request-1")
        self.assertEqual(event["credit_debit_eur"], "0.0000031")
        self.assertEqual(event["debit_observation_status"], "observed")
        self.assertEqual(event["content_parse_status"], "parsed")
        self.assertEqual(event["usage_parse_status"], "parsed")
        self.assertIsNone(event["stage"])
        self.assertIsNone(event["run_id"])
        self.assertIsNone(event["target_id"])
        self.assertIsNotNone(event["invocation_id"])
        self.assertIsNotNone(event["dispatch_id"])
        rendered = json.dumps(events)
        for secret in ("secret prompt", "secret user", "owned-fixture-key", "authorization", "127.0.0.1"):
            self.assertNotIn(secret, rendered)

    def test_retry_is_two_dispatches_not_two_invocations(self):
        events = []
        with provider([response({"error": "busy"}, status=503), response(request_id="request-2")]) as seen:
            llm = self.client(events)
            self.assertEqual(llm.complete("s", "u"), ["OK"])
        self.assertEqual(len(seen), 2)
        self.assertEqual([e["retry_index"] for e in events], [0, 1])
        self.assertEqual(events[0]["transport_status"], "http_error")
        self.assertIsNone(events[0]["credit_debit_eur"])
        self.assertEqual(len({e["dispatch_id"] for e in events}), 2)
        self.assertEqual(len({e["invocation_id"] for e in events}), 1)
        self.assertEqual(llm.usage.calls, 1)

    def test_timeout_is_actual_dispatch_unknown_not_zero(self):
        events = []
        with provider([response(delay=.15)]):
            llm = self.client(events, http_timeout=.03)
            llm.max_attempts = 1
            with self.assertRaises(TimedOutError):
                llm.complete("s", "u")
        self.assertEqual(events[0]["transport_status"], "timeout")
        self.assertEqual(events[0]["debit_observation_status"], "unknown")
        self.assertIsNone(events[0]["credit_debit_eur"])
        self.assertFalse(events[0]["received_body"])

    def test_malformed_json_has_body_but_unknown_billing(self):
        events = []
        with provider([response(b"not JSON")]):
            llm = self.client(events)
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertTrue(events[0]["received_body"])
        self.assertEqual(events[0]["body_parse_status"], "failed")
        self.assertEqual(events[0]["transport_status"], "response_received")
        self.assertIsNone(events[0]["credit_debit_eur"])
        self.assertEqual(len(events), 1)

    def test_valid_object_malformed_content_has_billing_before_error(self):
        events = []
        with provider([response(dict(GOOD, choices=[{"message": {"content": ["wrong"]}}]))]):
            llm = self.client(events)
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertEqual(events[0]["content_parse_status"], "failed")
        self.assertEqual(events[0]["credit_debit_eur"], "0.0000031")

    def test_missing_invalid_and_energy_billing_never_credit_zero(self):
        for bill in (None, {"credits": "NaN", "paid_with": "credits"},
                     {"credits": "0.25", "paid_with": "energy"}):
            with self.subTest(bill=bill):
                events = []
                with provider([response(dict(GOOD, billing_cost=bill))]):
                    self.client(events).complete("s", "u")
                self.assertIsNone(events[0]["credit_debit_eur"])
                self.assertIn(events[0]["debit_observation_status"], ("unknown", "noncredit"))

    def test_terminal_error_keeps_actual_dispatch_not_retry(self):
        for status, error in ((410, ModelUnavailableError), (402, QuotaExhaustedError)):
            with self.subTest(status=status):
                events = []
                with provider([response({"error": "owned-fixture-key"}, status=status)]), self.assertRaises(error):
                    self.client(events).complete("s", "u")
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["http_status"], status)
                self.assertNotIn("owned-fixture-key", json.dumps(events))

    def test_billed_http_error_retained_without_claiming_success(self):
        events = []
        with provider([response({"billing_cost": BILL}, status=402)]):
            llm = self.client(events)
            with self.assertRaises(QuotaExhaustedError):
                llm.complete("s", "u")
        self.assertEqual(events[0]["credit_debit_eur"], "0.0000031")
        self.assertEqual(events[0]["transport_status"], "http_error")
        self.assertEqual(llm.usage.calls, 0)

    def test_cache_hit_has_no_dispatch_id(self):
        events = []
        with tempfile.TemporaryDirectory() as temp, provider([response()]) as seen:
            llm = self.client(events, cache_path=Path(temp) / "cache.db")
            llm.complete("s", "u")
            llm.complete("s", "u")
            llm.cache.conn.close()
        self.assertEqual(len(seen), 1)
        self.assertEqual([e["event_type"] for e in events], ["dispatch", "cache_hit"])
        self.assertIsNone(events[1]["dispatch_id"])
        self.assertIsNone(events[1]["credit_debit_eur"])

    def test_budget_refusal_has_no_dispatch_or_server_request(self):
        events = []
        with provider([]) as seen:
            llm = self.client(events, budget_usd=0)
            with self.assertRaises(BudgetExceeded):
                llm.complete("s", "u")
        self.assertEqual(seen, [])
        self.assertEqual(events[0]["event_type"], "budget_refusal")
        self.assertIsNone(events[0]["dispatch_id"])

    def test_predispatch_invalid_payload_separate(self):
        events = []
        with provider([]) as seen:
            llm = self.client(events)
            with self.assertRaises(TypeError):
                llm.complete(object(), "u")
        self.assertEqual(seen, [])
        self.assertEqual(events[0]["event_type"], "pre_dispatch_error")
        self.assertIsNone(events[0]["dispatch_id"])

    def test_multiple_completions_have_distinct_invocations_and_dispatches(self):
        events = []
        with provider([response(), response(request_id="request-2")]):
            llm = self.client(events)
            llm.complete("s", "u1")
            llm.complete("s", "u2")
        self.assertEqual(len({e["invocation_id"] for e in events}), 2)
        self.assertEqual(len({e["dispatch_id"] for e in events}), 2)
        self.assertEqual(llm.usage.provider_billing["provider_credit_debit_eur"], "0.0000062")

    def test_explicit_metadata_and_credential_echo_filter(self):
        events = []
        with provider([response(request_id="owned-fixture-key")]):
            llm = self.client(events, dispatch_context={"run_id": "run-7", "target_id": "target-2",
                                                      "stage": "assessor", "prompt": "never store"})
            llm.complete("s", "u")
        self.assertEqual(events[0]["run_id"], "run-7")
        self.assertEqual(events[0]["target_id"], "target-2")
        self.assertEqual(events[0]["stage"], "assessor")
        self.assertIsNone(events[0]["provider_request_id"])
        self.assertNotIn("never store", json.dumps(events))

    def test_no_ledger_is_no_retention_billing_still_fixed(self):
        with provider([response(dict(GOOD, usage="broken"))]):
            llm = HTTPLLM("melious/glm-5.3-flash", api_key="owned-fixture-key")
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertIsNone(llm.dispatch_ledger)
        self.assertEqual(llm.usage.provider_billing["provider_credit_debit_eur"], "0.0000031")

    def test_anthropic_schema_failure_retains_credits(self):
        events = []
        with provider([response({"content": "broken", "billing_cost": BILL})]):
            llm = HTTPLLM("anthropic/claude-sonnet-4-5", api_key="owned-fixture-key", dispatch_ledger=events)
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertEqual(llm.usage.provider_billing["provider_credit_debit_eur"], "0.0000031")

    def test_direct_post_has_explicitly_missing_invocation(self):
        events = []
        with provider([response()]):
            llm = self.client(events)
            llm._post(llm.base_url + "/chat/completions", {}, {})
        self.assertIsNone(events[0]["invocation_id"])
        self.assertIsNotNone(events[0]["dispatch_id"])


    def test_connection_refusal_preserves_each_dispatch(self):
        events = []
        with patch.dict(os.environ, {"JITTEST_MODEL_PRICE": "1,3"}):
            llm = self.client(events)
            llm.base_url = "http://127.0.0.1:0/v1"
            with self.assertRaises(LLMError):
                llm.complete("s", "u")
        self.assertEqual(len(events), 2)
        self.assertEqual([e["transport_status"] for e in events], ["transport_error"] * 2)
        self.assertTrue(all(e["credit_debit_eur"] is None for e in events))

    def test_summary_has_unknowns_and_no_invented_wallet_total(self):
        events = []
        with provider([response({"error": "busy"}, status=503), response()]):
            llm = self.client(events)
            llm.complete("s", "u")
        summary = summarize_dispatch_ledger(events)
        self.assertEqual(summary["actual_dispatches"], 2)
        self.assertEqual(summary["retry_dispatches"], 1)
        self.assertEqual(summary["known_invocations"], 1)
        self.assertEqual(summary["unknown_debit_dispatches"], 1)
        self.assertEqual(summary["observed_credit_debit_eur"], "0.0000031")
        self.assertFalse(summary["wallet_invoice_reconciled"])
        self.assertIsNone(summary["total_reconciled_provider_usd"])
        self.assertIsNone(summary["ci_runtime_expense_usd"])

    def test_summary_rejects_duplicate_dispatch_and_conflicting_debit(self):
        events = []
        with provider([response()]):
            self.client(events).complete("s", "u")
        with self.assertRaises(ValueError):
            summarize_dispatch_ledger(events + events)
        for change in ({"credit_debit_eur": "NaN"}, {"credit_debit_eur": "-1"},
                       {"debit_observation_status": "unknown"}, {"dispatch_id": None},
                       {"retry_index": True}, {"received_body": False}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([dict(events[0], **change)])

    def test_summary_empty_is_unmeasured_not_zero_total(self):
        result = summarize_dispatch_ledger([])
        self.assertEqual(result["actual_dispatches"], 0)
        self.assertIsNone(result["observed_credit_debit_eur"])
        self.assertIsNone(result["total_reconciled_provider_usd"])

    def test_summary_nondispatch_cannot_invent_dispatch_or_debit(self):
        events = []
        with provider([]):
            llm = self.client(events, budget_usd=0)
            with self.assertRaises(BudgetExceeded):
                llm.complete("s", "u")
        for change in ({"dispatch_id": "fabricated"}, {"credit_debit_eur": "0"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([dict(events[0], **change)])


    def test_corrupt_cache_is_not_a_dispatch_and_records_parse_failure(self):
        events = []
        with tempfile.TemporaryDirectory() as temp, provider([]) as seen:
            llm = self.client(events, cache_path=Path(temp) / "cache.db")
            # Cache lookup sees retained bytes, but decoding fails before transport.
            import hashlib
            key = hashlib.sha256(
                f"{llm.provider}|{llm.model_name}|s|u|1|{llm.temperature}".encode()).hexdigest()
            llm.cache.put(key, "not JSON")
            with self.assertRaises(ValueError):
                llm.complete("s", "u")
            llm.cache.conn.close()
        self.assertEqual(seen, [])
        self.assertEqual(events[0]["event_type"], "cache_hit")
        self.assertIsNone(events[0]["dispatch_id"])
        self.assertEqual(events[0]["body_parse_status"], "failed")
        self.assertEqual(summarize_dispatch_ledger(events)["body_parse_failures"], 1)


class DispatchLedgerSchema(unittest.TestCase):
    """Pure declared schema fixtures, not owner/provider statement evidence."""

    @staticmethod
    def event(**changes):
        value = {
            "schema_version": 1, "event_type": "dispatch", "run_id": None,
            "target_id": None, "stage": None, "invocation_id": "invocation-1",
            "dispatch_id": "dispatch-1", "retry_index": 0,
            "dispatch_timestamp_utc": "2026-09-30T17:00:00+00:00",
            "provider_request_id": None, "http_status": 200,
            "transport_status": "response_received", "received_body": True,
            "body_parse_status": "parsed", "content_parse_status": "parsed",
            "usage_parse_status": "parsed", "credit_debit_eur": "0.25",
            "provider_equivalent_eur": "0.25", "debit_observation_status": "observed",
            "fx_receipt_sha256": None, "sanitized_statement_line_id": None,
        }
        value.update(changes)
        return value

    def test_nondict_event_is_typed_value_error(self):
        for value in (None, [], "dispatch", 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_dispatch_ledger([value])

    def test_invalid_or_missing_dispatch_timestamp_is_rejected(self):
        for stamp in (None, 1, True, "yesterday", "2026-09-30T17:00:00",
                      "2026-09-30T17:00:00+05:30", "2026-02-30T17:00:00Z"):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                summarize_dispatch_ledger([self.event(dispatch_timestamp_utc=stamp)])

    def test_present_but_malformed_context_and_ids_refuse(self):
        for field, value in (("run_id", ""), ("run_id", {}), ("target_id", 0),
                             ("target_id", "contains whitespace"), ("stage", "invented"),
                             ("stage", []), ("provider_request_id", ""),
                             ("provider_request_id", True), ("invocation_id", "bad id"),
                             ("dispatch_id", "bad id")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                summarize_dispatch_ledger([self.event(**{field: value})])

    def test_noncredit_requires_received_parsed_body_and_finite_equivalent(self):
        base = self.event(debit_observation_status="noncredit", credit_debit_eur=None)
        for change in ({"transport_status": "timeout"}, {"received_body": False},
                       {"body_parse_status": "failed"}, {"provider_equivalent_eur": None},
                       {"provider_equivalent_eur": "NaN"}, {"provider_equivalent_eur": "-1"},
                       {"provider_equivalent_eur": 0.25}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([dict(base, **change)])

    def test_observed_requires_parsed_body_and_matching_equivalent(self):
        for change in ({"body_parse_status": "failed"}, {"provider_equivalent_eur": "NaN"},
                       {"provider_equivalent_eur": "0.5"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([self.event(**change)])

    def test_invalid_transport_body_usage_and_status_combinations_refuse(self):
        for change in ({"schema_version": True}, {"schema_version": 1.0},
                       {"event_type": []}, {"transport_status": []}, {"http_status": True}, {"http_status": "200"}, {"http_status": 999},
                       {"transport_status": "http_error", "http_status": 200},
                       {"received_body": "yes"}, {"body_parse_status": "invented"},
                       {"content_parse_status": "invented"}, {"usage_parse_status": "invented"},
                       {"usage_parse_status": "parsed", "content_parse_status": "failed"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([self.event(**change)])

    def test_none_context_is_valid_unknown_and_batch_retry_resets_are_valid(self):
        batch = [self.event(), self.event(dispatch_id="dispatch-2")]
        result = summarize_dispatch_ledger(batch)
        self.assertEqual(result["actual_dispatches"], 2)
        self.assertEqual(result["retry_dispatches"], 0)
        self.assertEqual(result["known_invocations"], 1)
        self.assertEqual(result["dispatches_missing_provider_request_id"], 2)
        self.assertEqual(result["dispatches_missing_run_target_or_stage"], 2)

    def test_missing_invocation_and_valid_noncredit_are_not_fabricated(self):
        event = self.event(invocation_id=None, credit_debit_eur=None,
                           debit_observation_status="noncredit")
        result = summarize_dispatch_ledger([event])
        self.assertEqual(result["events_missing_invocation"], 1)
        self.assertEqual(result["noncredit_dispatches"], 1)
        self.assertIsNone(result["observed_credit_debit_eur"])

    def test_nondispatch_cannot_claim_response_or_timestamp(self):
        event = self.event(event_type="cache_hit", dispatch_id=None, retry_index=None,
                           dispatch_timestamp_utc=None, transport_status="not_dispatched",
                           http_status=None, provider_request_id=None, received_body=False,
                           content_parse_status="not_attempted", usage_parse_status="not_attempted",
                           credit_debit_eur=None, provider_equivalent_eur=None,
                           debit_observation_status="unknown")
        for change in ({"dispatch_timestamp_utc": "2026-09-30T17:00:00Z"},
                       {"transport_status": "response_received"}, {"received_body": True},
                       {"provider_request_id": "request-1"}, {"http_status": 200}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_dispatch_ledger([dict(event, **change)])


if __name__ == "__main__":
    unittest.main()
