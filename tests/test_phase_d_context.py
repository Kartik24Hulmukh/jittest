"""Unit tests for Phase D ContextCompiler."""

import tempfile
from pathlib import Path
from jittest.phase_d.context import ContextCompiler, TargetContext


def test_context_compiler_nearest_tests_and_conftest():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "src").mkdir()
        (repo / "tests").mkdir()

        (repo / "conftest.py").write_text("@pytest.fixture\ndef app(): return None\n")
        (repo / "tests" / "test_app.py").write_text(
            "def test_my_symbol():\n    result = my_symbol(10)\n    assert result == 20\n"
        )
        (repo / "src" / "app.py").write_text("def my_symbol(x):\n    return x * 2\n")

        compiler = ContextCompiler(repo)
        ctx = compiler.compile_context(
            target_symbol="my_symbol",
            target_file="src/app.py",
            after_source="def my_symbol(x):\n    return x * 2\n",
        )

        assert ctx.target_symbol == "my_symbol"
        assert len(ctx.test_function_bodies) == 1
        assert "def test_my_symbol():" in ctx.test_function_bodies[0]
        assert len(ctx.conftest_fragments) == 1
        assert "app()" in ctx.conftest_fragments[0]

        formatted = ctx.format_for_prompt(max_bytes=1000)
        assert "my_symbol" in formatted
        assert "test_my_symbol" in formatted
