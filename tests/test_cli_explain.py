"""jittest explain: stable JSON contract and exit-code table."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from jittest import receipt as R
from jittest.cli import main
from jittest.explain import EXIT_CODES, HINTS, explain_receipt
from tests.test_receipt_json_schema import _minimal_receipt


class ExplainTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        d = Path(self.td.name)
        self.good = d / "good.json"
        self.good.write_text(json.dumps(R.sign_evidence(_minimal_receipt(), key_path=d / "k")))
        tampered = json.loads(self.good.read_text())
        tampered["verdict"] = "refuted"
        tampered["proven_catch"] = False
        self.bad = d / "bad.json"
        self.bad.write_text(json.dumps(tampered))

    def tearDown(self):
        self.td.cleanup()

    def test_tables_cover_same_codes(self):
        self.assertEqual(set(EXIT_CODES), set(HINTS))
        self.assertEqual(set(EXIT_CODES), {0, 2, 3, 4, 5, 6, 7})

    def test_good_receipt_exit_zero_and_json_keys(self):
        info = explain_receipt(self.good)
        self.assertEqual(info["exit_code"], 0)
        self.assertEqual(info["code"], "ok")
        for k in ("explain_version", "checks", "provenance", "sandbox", "hint", "verdict_text"):
            self.assertIn(k, info)
        self.assertTrue(info["checks"]["signature_valid"])

    def test_tampered_receipt_exit_two(self):
        info = explain_receipt(self.bad)
        self.assertEqual(info["exit_code"], 2)
        self.assertEqual(info["code"], "signature_invalid")
        self.assertIn("original artifact", info["hint"])

    def test_require_confined_on_unconfined_is_seven(self):
        d = Path(self.td.name)
        rec = _minimal_receipt()
        rec["sandbox"] = {"mode": "off", "backend": "none", "image": None, "isolated": False,
                          "network_denied": False, "notes": []}
        p = d / "unconfined.json"
        p.write_text(json.dumps(R.sign_evidence(rec, key_path=d / "k2")))
        self.assertEqual(explain_receipt(p, require_confined=True)["exit_code"], 7)

    def test_cli_json_and_text(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["explain", str(self.good), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["exit_code"], 0)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["explain", str(self.bad)])
        self.assertEqual(rc, 2)
        self.assertIn("hint", buf.getvalue())
        self.assertIn("REFUSED", buf.getvalue())

    def test_missing_file_never_raises(self):
        info = explain_receipt(Path(self.td.name) / "nope.json")
        self.assertNotEqual(info["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
