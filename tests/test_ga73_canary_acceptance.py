"""Acceptance rejects empty, single-run, unpaired and low-confidence canaries."""
import copy
import unittest

from eval.ga73_canary import acceptance


class CanaryAcceptanceTests(unittest.TestCase):
    def test_requires_two_real_confident_paired_catches(self):
        row = {'findings': [{'assessment': {'verdict': 'real_regression', 'confidence': 0.8,
                                            'should_report': True}}],
               'telemetry': [{'disposition': 'catching', 'base_outcome': 'pass', 'head_outcome': 'fail'}]}
        self.assertFalse(acceptance([]))
        self.assertFalse(acceptance([row]))
        self.assertTrue(acceptance([row, row]))
        for field, value in [('verdict', 'intended_change'), ('confidence', 0.69), ('should_report', False)]:
            broken = copy.deepcopy(row)
            broken['findings'][0]['assessment'][field] = value
            self.assertFalse(acceptance([row, broken]))
        broken = copy.deepcopy(row)
        broken['telemetry'][0]['base_outcome'] = 'fail'
        self.assertFalse(acceptance([row, broken]))
