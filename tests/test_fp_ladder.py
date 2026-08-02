"""The ladder must decide the question, or say that it cannot.

The failure this guards against is not a crash. It is a ladder that comes back
with three numbers and lets a reader pick the story they already believed.
Every verdict here is pinned to the exact shape of counts that produces it,
including the two shapes that must refuse to conclude anything.
"""
from __future__ import annotations

import unittest

from eval.fp_ladder import (
    GATE_NOT_BINDING,
    GATE_WAS_BINDING,
    INCONCLUSIVE,
    UPSTREAM,
    ladder_verdict,
    parse_thresholds,
    refutation_condition,
    verdict_note,
)


def _rung(threshold, requests):
    return {"risk_threshold": threshold, "model_requests_total": requests}


class Thresholds(unittest.TestCase):
    def test_parsed_descending(self):
        self.assertEqual(parse_thresholds("0.0,0.35,0.15"), [0.35, 0.15, 0.0])

    def test_duplicates_collapse(self):
        self.assertEqual(parse_thresholds("0.35, 0.35 ,0.0"), [0.35, 0.0])

    def test_blank_chunks_tolerated(self):
        self.assertEqual(parse_thresholds("0.35,,0.0,"), [0.35, 0.0])

    def test_out_of_range_is_rejected(self):
        # A threshold above 1.0 admits nothing and looks like a broken
        # extractor; below 0.0 admits everything and looks like a fixed gate.
        # Both would be misread as findings.
        for bad in ("1.5", "-0.1"):
            with self.assertRaises(ValueError):
                parse_thresholds(bad)

    def test_empty_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_thresholds(" , ")


class RefutationCondition(unittest.TestCase):
    def test_a_zero_floor_states_the_decisive_test(self):
        text = refutation_condition([0.35, 0.0])
        self.assertIn("still 0 at threshold 0.0", text)
        self.assertIn("upstream", text)

    def test_a_nonzero_floor_refuses_to_exonerate_the_gate(self):
        text = refutation_condition([0.35, 0.15])
        self.assertIn("does not exonerate", text)
        self.assertIn("Re-run including 0.0", text)


class Verdicts(unittest.TestCase):
    def test_zero_everywhere_with_an_open_gate_points_upstream(self):
        rungs = [_rung(0.35, 0), _rung(0.15, 0), _rung(0.0, 0)]
        self.assertEqual(ladder_verdict(rungs), UPSTREAM)

    def test_zero_everywhere_without_an_open_gate_concludes_nothing(self):
        # This is the important one. Three zeros look like overwhelming
        # evidence, and without a 0.0 rung they are not evidence at all.
        rungs = [_rung(0.35, 0), _rung(0.15, 0)]
        self.assertEqual(ladder_verdict(rungs), INCONCLUSIVE)

    def test_rising_requests_means_the_gate_was_binding(self):
        rungs = [_rung(0.35, 0), _rung(0.15, 12), _rung(0.0, 40)]
        self.assertEqual(ladder_verdict(rungs), GATE_WAS_BINDING)

    def test_flat_nonzero_requests_means_the_gate_was_not_binding(self):
        rungs = [_rung(0.35, 22), _rung(0.15, 22), _rung(0.0, 22)]
        self.assertEqual(ladder_verdict(rungs), GATE_NOT_BINDING)

    def test_falling_requests_is_not_silently_filed_as_binding(self):
        # Loosening a filter cannot admit fewer targets. If it appears to,
        # something else moved and the run is not a controlled experiment.
        rungs = [_rung(0.35, 40), _rung(0.15, 30), _rung(0.0, 10)]
        self.assertEqual(ladder_verdict(rungs), INCONCLUSIVE)

    def test_a_single_rung_decides_nothing(self):
        self.assertEqual(ladder_verdict([_rung(0.0, 5)]), INCONCLUSIVE)

    def test_no_rungs_decides_nothing(self):
        self.assertEqual(ladder_verdict([]), INCONCLUSIVE)


class Notes(unittest.TestCase):
    def test_every_verdict_has_a_note(self):
        for verdict in (UPSTREAM, GATE_WAS_BINDING, GATE_NOT_BINDING, INCONCLUSIVE):
            self.assertTrue(verdict_note(verdict))

    def test_the_upstream_note_forbids_tuning_risk_on_this_run(self):
        self.assertIn("Do not tune risk.py", verdict_note(UPSTREAM))

    def test_the_binding_note_refuses_to_recommend_the_trade(self):
        note = verdict_note(GATE_WAS_BINDING)
        self.assertIn("false-positive rate", note)


class ImportDiscipline(unittest.TestCase):
    def test_the_module_does_not_import_jittest_at_module_scope(self):
        # ci.yml runs the whole tree once with no third-party packages
        # installed. A module-level import of the package under test turns
        # that step red at collection time, which has happened before.
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[1]
            / "eval"
            / "fp_ladder.py"
        ).read_text(encoding="utf-8")
        head = source.split("def run_rung", 1)[0]
        self.assertNotIn("\nfrom jittest", head)
        self.assertNotIn("\nimport jittest", head)


if __name__ == "__main__":
    unittest.main()
