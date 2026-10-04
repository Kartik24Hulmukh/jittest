"""Issue #73 cost gate: wallet reconciliation must be exact and fail closed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import reconcile_wallet  # noqa: E402


def _artifact(rows):
    return {"sha": "0" * 40, "rows": rows}


def _ok_row(debit):
    return {"case": "completion", "status": "ok",
            "provider_billing": None if debit is None else {
                "provider_cost_eur": debit, "provider_credit_debit_eur": debit,
                "provider_response_count": 1, "provider_billing_complete": True}}


def _failed_row():
    return {"case": "completion", "status": "failed",
            "error_type": "InsufficientCreditsError"}


def _wallet(opening="10.00000000", closing="9.99000000", topups="0",
            invoiced=None, **overrides):
    data = {"schema": "jittest/wallet-export/1", "source": "melious-dashboard",
            "currency": "EUR", "period_start": "2026-10-04T00:00:00Z",
            "period_end": "2026-10-04T23:59:59Z", "opening_balance": opening,
            "closing_balance": closing, "topups_total": topups,
            "invoiced_total": invoiced}
    data.update(overrides)
    return data


class ReconcileWalletTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _write(self, name, obj):
        path = self.root / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        return path

    def test_template_is_valid_and_tagged(self):
        self.assertEqual(reconcile_wallet.main(["--print-template"]), 0)
        template = reconcile_wallet.WALLET_TEMPLATE
        self.assertEqual(template["schema"], "jittest/wallet-export/1")
        for field in ("opening_balance", "closing_balance", "topups_total"):
            self.assertIsInstance(template[field], str)

    def test_consistent_reconciliation_exact_decimal(self):
        artifact = self._write("a.json", _artifact(
            [_ok_row("0.001"), _ok_row("0.002"), _ok_row("0.007"), _failed_row()]))
        wallet = self._write("w.json", _wallet(opening="10.00000000",
                                               closing="9.98000000"))
        out = self.root / "report.json"
        rc = reconcile_wallet.main(["--wallet", str(wallet),
                                    "--artifact", str(artifact),
                                    "--out", str(out)])
        self.assertEqual(rc, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["received_credit_debits"], "0.010")
        self.assertEqual(report["wallet_observed_spend"], "0.02000000")
        # wallet spend (0.02) minus received debits (0.01): the failed call's
        # unobserved spend is bounded, never assumed zero.
        self.assertEqual(report["implied_unaccounted_spend"], "0.01000000")
        self.assertEqual(report["failed_or_unreceived_calls"], 1)
        self.assertEqual(report["completion_calls"], 4)
        self.assertTrue(report["consistent"])
        self.assertTrue(report["non_claims"])

    def test_topups_count_toward_spend(self):
        artifact = self._write("a.json", _artifact([_ok_row("5.00")]))
        wallet = self._write("w.json", _wallet(opening="1.00", closing="6.00",
                                               topups="10.00"))
        out = self.root / "r.json"
        rc = reconcile_wallet.main(["--wallet", str(wallet),
                                    "--artifact", str(artifact),
                                    "--out", str(out)])
        self.assertEqual(rc, 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["wallet_observed_spend"], "5.00")
        self.assertEqual(report["implied_unaccounted_spend"], "0.00")

    def test_debits_exceeding_wallet_spend_fail_closed(self):
        artifact = self._write("a.json", _artifact([_ok_row("3.00")]))
        wallet = self._write("w.json", _wallet(opening="10.00", closing="9.00"))
        self.assertEqual(reconcile_wallet.main(
            ["--wallet", str(wallet), "--artifact", str(artifact),
             "--out", str(self.root / "r.json")]), 1)

    def test_invoice_mismatch_fails_closed(self):
        artifact = self._write("a.json", _artifact([_ok_row("1.00")]))
        wallet = self._write("w.json", _wallet(opening="10.00", closing="9.00",
                                               invoiced="2.50"))
        out = self.root / "r.json"
        self.assertEqual(reconcile_wallet.main(
            ["--wallet", str(wallet), "--artifact", str(artifact),
             "--out", str(out)]), 1)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertIs(report["invoice_matches_wallet_delta"], False)

    def test_ok_call_without_billing_row_is_counted_not_zero_rated(self):
        artifact = self._write("a.json", _artifact([_ok_row(None)]))
        wallet = self._write("w.json", _wallet(opening="1.00", closing="0.50"))
        out = self.root / "r.json"
        self.assertEqual(reconcile_wallet.main(
            ["--wallet", str(wallet), "--artifact", str(artifact),
             "--out", str(out)]), 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["ok_calls_without_billing_row"], 1)
        self.assertEqual(report["received_credit_debits"], "0")

    def test_malformed_wallet_rejected(self):
        artifact = self._write("a.json", _artifact([_ok_row("0.01")]))
        for bad in (_wallet(schema="wrong"), _wallet(opening="-1.00"),
                    _wallet(closing="abc"), _wallet(opening="1e999"),
                    _wallet(opening=True), _wallet(source=""),
                    _wallet(invoiced="NaN")):
            wallet = self._write("w.json", bad)
            rc = reconcile_wallet.main(
                ["--wallet", str(wallet), "--artifact", str(artifact)])
            self.assertEqual(rc, 2, msg=bad)

    def test_malformed_artifact_rejected(self):
        wallet = self._write("w.json", _wallet())
        for bad in ({"no_rows": True}, {"rows": "nope"},
                    _artifact([{"case": "completion", "status": "ok",
                                "provider_billing": {"provider_credit_debit_eur": 5}}])):
            artifact = self._write("a.json", bad)
            self.assertEqual(reconcile_wallet.main(
                ["--wallet", str(wallet), "--artifact", str(artifact)]), 2)

    def test_currency_and_period_validation(self):
        for bad in (_wallet(currency="USD"), _wallet(period_start="placeholder"),
                    _wallet(period_end="2026-10-03T00:00:00Z"),
                    _wallet(period_start="2026-10-04T00:00:00")):
            with self.assertRaises(reconcile_wallet.InputError):
                reconcile_wallet.load_wallet(self._write("w.json", bad))

    def test_duplicate_json_keys_and_nonfinite_constants_rejected(self):
        for raw in ('{"rows": [], "rows": []}', '{"rows": [], "extra": NaN}'):
            path = self.root / "bad.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaises(reconcile_wallet.InputError):
                reconcile_wallet.load_artifact(path)
        path = self.root / "bad-wallet.json"
        path.write_text('{"schema": "wrong", "schema": "jittest/wallet-export/1"}')
        with self.assertRaises(reconcile_wallet.InputError):
            reconcile_wallet.load_wallet(path)

    def test_duplicate_artifact_bytes_rejected_even_under_different_paths(self):
        a1 = reconcile_wallet.load_artifact(self._write("a1.json", _artifact([_ok_row("0.001")])))
        a2 = reconcile_wallet.load_artifact(self._write("a2.json", _artifact([_ok_row("0.001")])))
        with self.assertRaises(reconcile_wallet.InputError):
            reconcile_wallet.reconcile(_wallet(), [a1, a2])

    def test_malformed_completion_and_empty_artifact_rejected(self):
        for rows in ([], [None], [{"case": "completion", "status": "bogus"}]):
            with self.assertRaises(reconcile_wallet.InputError):
                reconcile_wallet.load_artifact(self._write("a.json", _artifact(rows)))

    def test_large_decimal_amounts_are_not_rounded(self):
        # Synthetic arithmetic fixture, never provider or wallet evidence.
        opening = "123456789012345678901234567890.00000001"
        closing = "123456789012345678901234567890.00000000"
        a = reconcile_wallet.load_artifact(self._write("a.json", _artifact([_ok_row("0.00000001")])))
        r = reconcile_wallet.reconcile(_wallet(opening=opening, closing=closing), [a])
        self.assertEqual(r["wallet_observed_spend"], "1E-8")
        self.assertEqual(r["implied_unaccounted_spend"], "0E-8")
        self.assertTrue(r["consistent"])

    def test_missing_arguments_are_usage_errors(self):
        self.assertEqual(reconcile_wallet.main([]), 2)
        wallet = self._write("w.json", _wallet())
        self.assertEqual(reconcile_wallet.main(["--wallet", str(wallet)]), 2)

    def test_multiple_artifacts_sum_across_runs(self):
        a1 = self._write("a1.json", _artifact([_ok_row("0.001"), _failed_row()]))
        a2 = self._write("a2.json", _artifact([_ok_row("0.002")]))
        wallet = self._write("w.json", _wallet(opening="1.000", closing="0.997"))
        out = self.root / "r.json"
        self.assertEqual(reconcile_wallet.main(
            ["--wallet", str(wallet), "--artifact", str(a1),
             "--artifact", str(a2), "--out", str(out)]), 0)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(report["received_credit_debits"], "0.003")
        self.assertEqual(report["completion_calls"], 3)
        self.assertEqual(report["failed_or_unreceived_calls"], 1)
        self.assertEqual(len(report["artifacts"]), 2)
        self.assertEqual(report["implied_unaccounted_spend"], "0.000")


if __name__ == "__main__":
    unittest.main()
