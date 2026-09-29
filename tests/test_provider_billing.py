import unittest

from jittest._billing import BillingTotals


class ProviderBilling(unittest.TestCase):
    def test_credits_are_exact_not_binary_float(self):
        b = BillingTotals()
        for _ in range(10):
            b.add({'credits': '0.000262', 'energy': '2.62', 'paid_with': 'credits'})
        self.assertEqual(b.as_dict()['provider_cost_eur'], '0.002620')
        self.assertEqual(b.as_dict()['provider_credit_debit_eur'], '0.002620')

    def test_energy_is_not_a_credit_debit(self):
        b = BillingTotals()
        b.add({'credits': '0.123', 'paid_with': 'energy'})
        self.assertEqual(b.as_dict()['provider_cost_eur'], '0.123')
        self.assertEqual(b.as_dict()['provider_credit_debit_eur'], '0')

    def test_missing_invalid_or_incomplete_billing_is_not_zero(self):
        for value in [None, {}, {'credits': 'NaN', 'paid_with': 'credits'},
                      {'credits': '-1', 'paid_with': 'credits'}, {'credits': 'Infinity', 'paid_with': 'energy'}]:
            b = BillingTotals()
            b.add({'credits': '0.1', 'paid_with': 'credits'})
            b.add(value)
            self.assertIsNone(b.as_dict()['provider_cost_eur'])
            self.assertFalse(b.as_dict()['provider_billing_complete'])

    def test_no_responses_is_unmeasured(self):
        self.assertIsNone(BillingTotals().as_dict()['provider_cost_eur'])


class HTTPBillingPropagation(unittest.TestCase):
    def test_normal_transport_retains_exact_provider_billing(self):
        import os
        from unittest.mock import patch

        from jittest.llm import HTTPLLM
        body = {'choices': [{'message': {'content': 'OK'}}],
                'usage': {'prompt_tokens': 19, 'completion_tokens': 3},
                'billing_cost': {'credits': '0.0000031', 'paid_with': 'credits'}}
        with patch.dict(os.environ, {'JITTEST_MODEL_PRICE': '1,3'}):
            llm = HTTPLLM('melious/glm-5.3-flash', api_key='unit-test')
            with patch.object(llm, '_post', return_value=body):
                self.assertEqual(llm.complete('system', 'user', n=2), ['OK', 'OK'])
        self.assertEqual(llm.usage.provider_billing['provider_cost_eur'], '0.0000062')
        self.assertTrue(llm.usage.provider_billing['provider_billing_complete'])
