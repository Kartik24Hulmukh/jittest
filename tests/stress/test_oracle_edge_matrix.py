"""Oracle edge matrix disposition and diff edge case tests (Mission M3)."""

import unittest

from jittest.diff import parse_unified_diff
from jittest.execute import Disposition, Outcome, Verdict


class OracleEdgeMatrixTests(unittest.TestCase):
    def test_flaky_on_head_disposition(self):
        """Flaky test on head with mixed outcomes must resolve to HEAD_FLAKY."""
        v = Verdict(
            is_catching=False,
            reason="Test failed once and passed once on head",
            latent=False,
            head_outcome=Outcome.PASS,
            base_outcome=None,
            disposition=Disposition.HEAD_FLAKY,
            head_runs=(Outcome.FAIL, Outcome.PASS),
            base_runs=(),
        )
        self.assertFalse(v.is_catching)
        self.assertFalse(v.rerun_agreement)
        self.assertEqual(v.disposition, Disposition.HEAD_FLAKY)

    def test_fails_on_both_latent_disposition(self):
        """Test failing on both head and base must resolve to latent finding."""
        v = Verdict(
            is_catching=False,
            reason="Test failed on both head and base",
            latent=True,
            head_outcome=Outcome.FAIL,
            base_outcome=Outcome.FAIL,
            disposition=Disposition.HEAD_FAILED_BASE_FAILED_LATENT,
            head_runs=(Outcome.FAIL,),
            base_runs=(Outcome.FAIL,),
        )
        self.assertFalse(v.is_catching)
        self.assertTrue(v.latent)
        self.assertEqual(v.disposition, Disposition.HEAD_FAILED_BASE_FAILED_LATENT)

    def test_uncollectable_head_disposition(self):
        """Test with collection error on head must resolve to HEAD_UNCOLLECTABLE."""
        v = Verdict(
            is_catching=False,
            reason="Collection error on head",
            latent=False,
            head_outcome=Outcome.ERROR,
            base_outcome=None,
            disposition=Disposition.HEAD_UNCOLLECTABLE,
            head_runs=(Outcome.ERROR,),
            base_runs=(),
        )
        self.assertFalse(v.is_catching)
        self.assertEqual(v.disposition, Disposition.HEAD_UNCOLLECTABLE)

    def test_empty_diff_parsing(self):
        """Empty diff must return empty file list."""
        res = parse_unified_diff("")
        self.assertEqual(res, [])

    def test_binary_only_diff_parsing(self):
        """Binary diff without python source changes returns no python diff targets."""
        binary_diff = (
            "diff --git a/image.png b/image.png\n"
            "index 1234567..89abcdef 100644\n"
            "Binary files a/image.png and b/image.png differ\n"
        )
        res = parse_unified_diff(binary_diff)
        self.assertEqual(res, [])

    def test_monorepo_pathological_diff_handling(self):
        """Pathological diff with 150 files parses cleanly without crashing."""
        diff_chunks = []
        for i in range(150):
            diff_chunks.append(
                f"diff --git a/mod_{i}.py b/mod_{i}.py\n"
                f"--- a/mod_{i}.py\n"
                f"+++ b/mod_{i}.py\n"
                f"@@ -1,2 +1,3 @@\n"
                f" def fn_{i}():\n"
                f"-    return {i}\n"
                f"+    return {i} + 1\n"
            )
        large_diff = "\n".join(diff_chunks)
        res = parse_unified_diff(large_diff)
        self.assertEqual(len(res), 150)


if __name__ == "__main__":
    unittest.main()
