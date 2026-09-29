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


class ProviderCredentialEcho(unittest.TestCase):
    def test_provider_error_body_cannot_echo_credential_into_report(self):
        import io
        import os
        import urllib.error
        from unittest.mock import patch

        from jittest.llm import HTTPLLM, ModelUnavailableError
        key = 'unit-credential-never-log-this'
        error = urllib.error.HTTPError('https://example.test', 404, 'Not Found', {},
                                      io.BytesIO(('invalid key: ' + key).encode()))
        with patch.dict(os.environ, {'JITTEST_MODEL_PRICE': '1,3'}):
            llm = HTTPLLM('melious/glm-5.3-flash', api_key=key)
            with patch('urllib.request.urlopen', side_effect=error), self.assertRaises(ModelUnavailableError) as raised:
                llm._post('https://example.test', {}, {})
        self.assertNotIn(key, str(raised.exception))


class ProviderBillingAbuse(unittest.TestCase):
    def test_extreme_decimal_metadata_is_withheld_without_panic(self):
        for cost in ['1E999999999', '1E-999999999', '9' * 10000]:
            b = BillingTotals()
            b.add({'credits': cost, 'paid_with': 'credits'})
            self.assertIsNone(b.as_dict()['provider_cost_eur'])


class HTTPUsageAbuse(unittest.TestCase):
    def test_invalid_usage_cannot_make_cost_negative_or_panic(self):
        import os
        from unittest.mock import patch

        from jittest.llm import HTTPLLM
        for value in [-1, float('inf'), True]:
            with patch.dict(os.environ, {'JITTEST_MODEL_PRICE': '1,3'}):
                llm = HTTPLLM('melious/glm-5.3-flash', api_key='unit-test')
                llm._account_response(value, value, 'prompt', 'text')
            self.assertTrue(llm.usage.tokens_estimated)
            self.assertGreater(llm.usage.cost_usd, 0)

    def test_malformed_json_is_a_typed_model_error(self):
        import io
        import os
        from unittest.mock import patch

        from jittest.llm import HTTPLLM, LLMError
        with patch.dict(os.environ, {'JITTEST_MODEL_PRICE': '1,3'}):
            llm = HTTPLLM('melious/glm-5.3-flash', api_key='unit-test')
            with patch('urllib.request.urlopen', return_value=io.BytesIO(b'not JSON')), self.assertRaises(LLMError):
                llm._post('https://example.test', {}, {})


class HTTPResponseSchemaAbuse(unittest.TestCase):
    def test_malformed_completion_schema_is_typed(self):
        import os
        from unittest.mock import patch

        from jittest.llm import HTTPLLM, LLMError
        for body in [{'choices': 'broken'}, {'choices': [{'message': None}]},
                     {'choices': [{'message': {'content': 'OK'}}], 'usage': 'broken'}]:
            with patch.dict(os.environ, {'JITTEST_MODEL_PRICE': '1,3'}):
                llm = HTTPLLM('melious/glm-5.3-flash', api_key='unit-test')
                with patch.object(llm, '_post', return_value=body), self.assertRaises(LLMError):
                    llm.complete('system', 'user')


class PriceSpecificity(unittest.TestCase):
    def test_small_model_does_not_borrow_base_model_price(self):
        import os
        from unittest.mock import patch

        from jittest._pricing import PRICES, price_for
        with patch.dict(os.environ, {}, clear=False):
            old = os.environ.pop('JITTEST_MODEL_PRICE', None)
            try:
                for model in ['gpt-4.1-mini', 'gpt-5-mini']:
                    self.assertEqual(price_for('openai/' + model), PRICES[model])
            finally:
                if old is not None:
                    os.environ['JITTEST_MODEL_PRICE'] = old
