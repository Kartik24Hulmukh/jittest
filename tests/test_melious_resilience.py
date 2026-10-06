"""The scripted-transport resilience evidence harness must stay green in CI.

These run the same scenarios that produce the committed evidence artifact, so
a regression in ceilings, failover, circuit bounding, or timeout enforcement
fails the suite instead of silently invalidating the evidence.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

try:
    import melious_resilience  # noqa: E402  (imports jittest.melious -> httpx)

    _HAVE_HTTPS = True
except ImportError:  # optional melious extra not installed
    _HAVE_HTTPS = False


@unittest.skipUnless(_HAVE_HTTPS, "requires the melious extra (httpx)")
class MeliousResilienceHarnessTests(unittest.TestCase):
    def test_all_scenarios_pass(self):
        evidence = melious_resilience.run_all()
        failures = [r for r in evidence["rows"] if r["status"] != "ok"]
        self.assertEqual(failures, [],
                         msg="resilience scenarios failed: "
                             + "; ".join(f"{r['case']}: {r['detail']}" for r in failures))
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["failed_checks"], 0)

    def test_every_declared_scenario_ran(self):
        evidence = melious_resilience.run_all()
        self.assertEqual({r["case"] for r in evidence["rows"]},
                         {name for name, _ in melious_resilience.SCENARIOS})
        self.assertIn("failover_latency", {r["case"] for r in evidence["rows"]})

    def test_failover_beats_the_200ms_bar(self):
        evidence = melious_resilience.run_all()
        row = next(r for r in evidence["rows"] if r["case"] == "failover_latency")
        self.assertEqual(row["status"], "ok")
        self.assertLess(row["elapsed_ms"], 200.0)


if __name__ == "__main__":
    unittest.main()
