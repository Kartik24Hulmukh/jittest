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
        dummy_code = "def my_fn(x):\n    return x * 2\n" + ("# padding line\n" * 100)
        (repo / "src" / "app.py").write_text(dummy_code)

        cfg = Config()
        llm = MockLLM()
        pipeline = PhaseDPipeline(repo, cfg, llm)

        telem = pipeline.process_target(
            target_symbol="my_fn",
            target_file="src/app.py",
            base_sha="base123",
            head_sha="head456",
            before_source=dummy_code,
            after_source=dummy_code,
            added_lines=[2],
        )

        assert telem.eligible
        assert telem.target_symbol == "my_fn"
        assert telem.candidate_sha != ""
        assert telem.final_disposition in (
            Disposition.ACCEPTED_STRONG_CATCH.value,
            Disposition.STABLE_TECHNICAL_WEAK_CATCH.value,
            Disposition.COLLECTION_IMPORT_FAILED.value,
        )
        assert telem.context_bytes > 2000
        assert "seed_first" in telem.model_calls_by_stage
