"""Unit tests for Phase D SeedFinder."""

import tempfile
from pathlib import Path
from jittest.phase_d.seed import SeedFinder


def test_seed_finder_discovers_seeds():
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "tests").mkdir()
        (repo / "tests" / "test_calc.py").write_text(
            "def test_add_numbers():\n    assert add(1, 2) == 3\n"
        )

        finder = SeedFinder(repo)
        seeds = finder.find_seed_tests("add", "src/calc.py")

        assert len(seeds) == 1
        assert seeds[0].test_name == "test_add_numbers"
        assert seeds[0].source_category == "seed_mutated"

        prompt = finder.format_seed_probe_prompt(seeds[0], "Target context info")
        assert "test_add_numbers" in prompt
        assert "Seed-First mode" in prompt
