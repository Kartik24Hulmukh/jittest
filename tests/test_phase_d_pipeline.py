"""Unit & integration tests for Phase D Pipeline."""

import tempfile
from pathlib import Path
from jittest.config import Config
from jittest.phase_d.pipeline_d import PhaseDPipeline
from jittest.phase_d.taxonomy import Disposition


class MockLLM:
    def __init__(self):
        self.calls = 0

    def complete(self, system: str, user: str, n: int = 1) -> list[str]:
        self.calls += 1
        return ["def test_target():\n    assert my_fn(10) == 20\n"]


def test_pipeline_d_target_processing():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def my_fn(x):\n    return x * 2\n")

        cfg = Config()
        llm = MockLLM()
        pipeline = PhaseDPipeline(repo, cfg, llm)

        telem = pipeline.process_target(
            target_symbol="my_fn",
            target_file="src/app.py",
            base_sha="base123",
            head_sha="head456",
            before_source="def my_fn(x):\n    return x * 2\n",
            after_source="def my_fn(x):\n    if x < 0: raise ValueError()\n    return x * 2\n",
            added_lines=[2],
        )

        assert telem.eligible
        assert telem.target_symbol == "my_fn"
        assert telem.candidate_sha != ""
        assert telem.final_disposition in (Disposition.ACCEPTED_STRONG_CATCH.value, Disposition.STABLE_TECHNICAL_WEAK_CATCH.value)
        assert telem.context_bytes > 0
        assert "seed_first" in telem.model_calls_by_stage
