"""Diff parsing and target extraction.

Written with unittest rather than pytest on purpose: the suite must run in an
environment where nothing can be installed, which is the same constraint the
mini-runner exists to satisfy.
"""
from __future__ import annotations

import unittest

from jittest.diff import (
    extract_targets,
    is_probably_test_file,
    parse_unified_diff,
)

from .helpers import FixtureRepo

SAMPLE = """diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -4,7 +4,6 @@ def apply_discount(price, percent):
     if percent < 0:
         raise ValueError("percent must not be negative")
     discounted = price - (price * percent / 100.0)
-    if discounted < 0:
-        return 0.0
-    return discounted
+    return round(discounted, 2)
diff --git a/newmod.py b/newmod.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/newmod.py
@@ -0,0 +1,2 @@
+def hello():
+    return "hi"
"""


class TestParseUnifiedDiff(unittest.TestCase):
    def test_line_numbers_and_flags(self):
        files = parse_unified_diff(SAMPLE)
        self.assertEqual(len(files), 2)

        calc = files[0]
        self.assertEqual(calc.path, "calc.py")
        self.assertEqual(calc.added_lines, [7])
        self.assertEqual(len(calc.removed_lines), 3)
        self.assertFalse(calc.is_new)

        newmod = files[1]
        self.assertTrue(newmod.is_new)
        self.assertEqual(newmod.added_lines, [1, 2])

    def test_malformed_input_is_not_fatal(self):
        self.assertEqual(parse_unified_diff(""), [])
        self.assertEqual(parse_unified_diff("not a diff at all\n@@ bogus @@"), [])


class TestTestFileDetection(unittest.TestCase):
    def test_positives(self):
        for path in ("tests/test_x.py", "test_x.py", "pkg/tests/helpers.py",
                     "pkg/calc_test.py", "conftest.py", "a/b/conftest.py"):
            self.assertTrue(is_probably_test_file(path), path)

    def test_negatives_that_merely_look_like_tests(self):
        for path in ("pkg/calc.py", "src/latest.py", "contest.py",
                     "src/protest/api.py"):
            self.assertFalse(is_probably_test_file(path), path)


class TestExtractTargets(unittest.TestCase):
    def test_returns_nothing_without_a_repo(self):
        self.assertEqual(extract_targets(SAMPLE), [])

    def test_extracts_the_changed_function_from_a_real_repo(self):
        with FixtureRepo() as repo:
            from jittest.diff import git_diff
            diff_text = git_diff(repo.path, repo.base, repo.head)
            targets = extract_targets(diff_text, repo=repo.path,
                                      base=repo.base, head=repo.head)

        self.assertEqual(len(targets), 1)
        t = targets[0]
        self.assertEqual(t.symbol, "apply_discount")
        self.assertEqual(t.file_path, "calc.py")
        self.assertIn("round(discounted", t.source_after)
        self.assertIn("return 0.0", t.source_before)
        self.assertTrue(t.modifies_existing)
        self.assertGreater(t.churn, 0)


if __name__ == "__main__":
    unittest.main()
