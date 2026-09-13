"""Source-level guard contract; hosted rehearsal verifies actual job skips."""
import unittest
from pathlib import Path


class ReleaseDryRun(unittest.TestCase):
    def test_every_side_effect_job_requires_a_tag_push(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/release.yml").read_text()
        for job in ("publish", "github-release", "update-floating-tag"):
            with self.subTest(job=job):
                # Identify only job-level fields, excluding nested steps.
                lines = workflow.split(f"\n  {job}:\n", 1)[1].splitlines()
                fields = []
                for line in lines:
                    if line.startswith("  ") and not line.startswith("    "):
                        break
                    if line.startswith("    if:"):
                        fields.append(line.strip())
                self.assertEqual(len(fields), 1)
                self.assertIn("github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v", fields[0])
                self.assertNotIn("||", fields[0])
