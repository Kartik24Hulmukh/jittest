"""Static scanner test ensuring no evidence-producing workflow contains hard-coded fabricated receipts."""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class NoFabricatedEvidenceTests(unittest.TestCase):
    def test_linux_evidence_workflow_has_no_fabricated_dict_literals(self):
        """Workflow .github/workflows/linux-evidence.yml must not write hard-coded dict literals to results JSON files."""
        wf_path = REPO_ROOT / ".github" / "workflows" / "linux-evidence.yml"
        self.assertTrue(wf_path.exists(), "linux-evidence.yml must exist")
        content = wf_path.read_text(encoding="utf-8")

        # Must invoke mutmut run for real
        self.assertIn("mutmut run", content, "mutmut-oracle job must invoke real `mutmut run`")

        # Scan python inline scripts for hard-coded summary dictionaries
        python_blocks = re.findall(r'python -c "(.*?)"', content, re.DOTALL)
        python_blocks += re.findall(r"python -c '(.*?)'", content, re.DOTALL)

        banned_hardcoded_keys = {"'total_mutants': 42", '"total_mutants": 42', "'killed': 38", '"killed": 38'}
        for block in python_blocks:
            for banned in banned_hardcoded_keys:
                self.assertNotIn(
                    banned,
                    block,
                    f"Found hard-coded summary dict literal {banned!r} in workflow script block. Evidence must be parsed from tool output."
                )

    def test_mutmut_oracle_parses_actual_tool_output(self):
        """mutmut-oracle job script must parse output from mutmut execution or log file."""
        wf_path = REPO_ROOT / ".github" / "workflows" / "linux-evidence.yml"
        content = wf_path.read_text(encoding="utf-8")
        self.assertIn("mutmut-run.log", content, "mutmut-oracle job must capture and upload mutmut-run.log")
        self.assertIn("partial", content, "mutmut-oracle job must support partial=true flag on timeout")


if __name__ == "__main__":
    unittest.main()
