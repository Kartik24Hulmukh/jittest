"""Adversarial safety tests for Phase D assertion checks."""

from jittest.safety import check_candidate


def test_standard_assert_recognized():
    code = "def test_foo():\n    assert 1 == 1\n"
    res = check_candidate(code)
    assert res.ok


def test_pytest_raises_recognized():
    code = "import pytest\ndef test_raises():\n    with pytest.raises(ValueError):\n        int('invalid')\n"
    res = check_candidate(code)
    assert res.ok


def test_unittest_self_assert_recognized():
    code = "def test_unittest(self):\n    self.assertEqual(1, 1)\n"
    res = check_candidate(code)
    assert res.ok


def test_pseudo_assert_method_rejected():
    code = "def test_fake():\n    mock.assert_called_with('foo')\n"
    res = check_candidate(code)
    assert not res.ok
    assert "no assertion" in res.reason
