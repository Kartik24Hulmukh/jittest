"""Pin the workflow <-> CLI contract checker (scripts/check_workflow_cli_contract.py).

Regression for PR #208 / the 2026-09-15 Gate-1 smoke dispatch that died in 0 s at
argparse, plus the third defect that PR did not cover (`--projects` vs `--project`).
"""

from __future__ import annotations

import importlib.util
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_workflow_cli_contract", ROOT / "scripts" / "check_workflow_cli_contract.py"
)
checker = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(checker)

SCRIPT = textwrap.dedent(
    """
    import argparse
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("--bugsinpy", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--budget", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=Path("eval-results.json"))
    ap.add_argument("--project", action="append", default=None)
    ap.add_argument("--dry-run", action="store_true")
    """
)

BROKEN_STEP = textwrap.dedent(
    """
    set -euo pipefail
    ARGS=()
    [ -z "$LIMIT" ] || ARGS+=(--limit "$LIMIT")
    [ -z "$PROJECTS" ] || ARGS+=(--projects "$PROJECTS")
    python eval/run_bugsinpy.py "${ARGS[@]}" 2>&1 | tee bugsinpy-run.log
    """
)

FIXED_STEP = textwrap.dedent(
    """
    set -euo pipefail
    ARGS=()
    [ -z "$LIMIT" ] || ARGS+=(--limit "$LIMIT")
    IFS=',' read -ra PROJ <<< "$PROJECTS"
    for p in "${PROJ[@]}"; do [ -z "$p" ] || ARGS+=(--project "$p"); done
    python eval/run_bugsinpy.py --bugsinpy /tmp/BugsInPy --out results.json "${ARGS[@]}" 2>&1 | tee log
    """
)

LATER = "path: |\n  results.json\n  bugsinpy-run.log\nrun: python eval/assert_measured.py results.json\n"


def _workflow(step: str) -> str:
    body = textwrap.indent(step.strip("\n"), " " * 10)
    return (
        "name: eval\non: workflow_dispatch\njobs:\n  bugsinpy-eval:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - name: Run\n        run: |\n" + body + "\n"
        "      - name: Upload\n        uses: actions/upload-artifact@v4\n        with:\n"
        "          path: |\n            results.json\n            bugsinpy-run.log\n"
        "      - name: Assert\n        run: python eval/assert_measured.py results.json\n"
    )


class ArgparseContractTests(unittest.TestCase):
    def test_contract_is_read_statically(self):
        c = checker.parse_argparse_contract(SCRIPT)
        self.assertEqual(c["required"], {"--bugsinpy"})
        self.assertIn("--project", c["options"])
        self.assertEqual(c["defaults"]["--out"], "eval-results.json")  # Path(...) unwrapped


class InvocationTests(unittest.TestCase):
    def test_pr208_shape_yields_all_three_defects(self):
        inv = checker.extract_invocations(BROKEN_STEP)[0]
        problems = checker.check_invocation(inv, checker.parse_argparse_contract(SCRIPT), LATER)
        joined = "\n".join(problems)
        self.assertIn("missing required flag --bugsinpy", joined)
        self.assertIn("unknown flag --projects", joined)
        self.assertIn("'eval-results.json'", joined)
        self.assertEqual(len(problems), 3)

    def test_fixed_shape_is_clean(self):
        inv = checker.extract_invocations(FIXED_STEP)[0]
        self.assertEqual(inv["flags"]["--bugsinpy"], "/tmp/BugsInPy")
        self.assertTrue(inv["dynamic"])
        self.assertEqual(inv["conditional"], {"--limit", "--project"})
        self.assertEqual(
            checker.check_invocation(inv, checker.parse_argparse_contract(SCRIPT), LATER), []
        )

    def test_conditional_required_flag_is_still_missing(self):
        step = 'ARGS=()\n[ -z "$B" ] || ARGS+=(--bugsinpy "$B")\npython eval/x.py "${ARGS[@]}"\n'
        inv = checker.extract_invocations(step)[0]
        problems = checker.check_invocation(inv, checker.parse_argparse_contract(SCRIPT), "")
        self.assertEqual(
            problems, ["missing required flag --bugsinpy (only conditionally appended)"]
        )

    def test_backslash_continuations_and_equals_form(self):
        step = "python scripts/x.py \\\n  --bugsinpy=/tmp/b \\\n  --out results.json\n"
        inv = checker.extract_invocations(step)[0]
        self.assertEqual(inv["flags"], {"--bugsinpy": "/tmp/b", "--out": "results.json"})

    def test_comments_and_non_repo_scripts_are_ignored(self):
        self.assertEqual(
            checker.extract_invocations("# python scripts/x.py --a\npython -m pytest\n"), []
        )


class WorkflowWalkTests(unittest.TestCase):
    def _repo(self, tmp: Path, step: str) -> Path:
        (tmp / ".github" / "workflows").mkdir(parents=True)
        (tmp / "eval").mkdir()
        (tmp / "eval" / "run_bugsinpy.py").write_text(SCRIPT, encoding="utf-8")
        (tmp / "eval" / "assert_measured.py").write_text("import argparse\n", encoding="utf-8")
        (tmp / ".github" / "workflows" / "eval.yml").write_text(_workflow(step), encoding="utf-8")
        return tmp

    def test_broken_repo_is_refused_and_fixed_repo_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            v = checker.check_workflows(self._repo(Path(d), BROKEN_STEP))
            self.assertEqual(len(v), 1)
            self.assertEqual(v[0]["job"], "bugsinpy-eval")
            self.assertEqual(len(v[0]["problems"]), 3)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(checker.check_workflows(self._repo(Path(d), FIXED_STEP)), [])

    def test_step_parser_reads_inline_and_block_run(self):
        jobs = checker.parse_workflow_steps(_workflow(FIXED_STEP))
        steps = jobs["bugsinpy-eval"]
        self.assertEqual(len(steps), 3)
        self.assertIn("--bugsinpy /tmp/BugsInPy", steps[0]["run"])
        self.assertIsNone(steps[1]["run"])
        self.assertEqual(steps[2]["run"], "python eval/assert_measured.py results.json")

    def test_missing_script_is_a_violation(self):
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            tmp = self._repo(Path(d), FIXED_STEP)
            (tmp / "eval" / "run_bugsinpy.py").unlink()
            v = checker.check_workflows(tmp)
            self.assertEqual(v[0]["problems"], ["script does not exist in repo"])

    def test_live_repository_workflows_honour_their_cli_contracts(self):
        violations = checker.check_workflows(ROOT)
        self.assertEqual(violations, [], violations)


if __name__ == "__main__":
    unittest.main()
