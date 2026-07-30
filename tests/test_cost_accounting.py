"""Lint probe: bound-method accounting helper only."""
from __future__ import annotations

from jittest.llm import Usage


class _Accountant:
    def __init__(self, model):
        from jittest.llm import HTTPLLM, BaseLLM
        self.model = model
        self.model_name = model.split("/")[-1]
        self.usage = Usage()
        self._price = HTTPLLM._price.__get__(self)
        self._account = HTTPLLM._account.__get__(self)
        self._account_response = HTTPLLM._account_response.__get__(self)
        assert issubclass(HTTPLLM, BaseLLM)
