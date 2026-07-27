"""Regression tests for Defect 28: strict UTF-8 decoding crashed on real repos.

A single Latin-1 byte anywhere in a tracked file made `git diff` output
undecodable, and jittest died with UnicodeDecodeError before it could do any
work. Older real-world repositories contain such bytes routinely, so this was a
hard crash on first run for an unknown but non-trivial share of target repos.

Two layers of defence are asserted here:
  1. behavioural - a repository containing non-UTF-8 bytes can be diffed and
     have its changed symbols extracted without raising.
  2. structural - every subprocess call in the shipped package that decodes
     output as text also passes an explicit `errors=` policy, so a new
     call site cannot silently reintroduce the crash.
"""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jittest.diff import extract_targets, git_diff, git_show

SRC = Path(__file__).resolve().parents[1] / "src" / "jittest"


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, errors="replace",
    )


class TestNonUtf8Repository(unittest.TestCase):
    """A Latin-1 byte in a source file must not stop the run."""

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        _git(self.repo, "init", "-q", "-b", "main", ".")
        _git(self.repo, "config", "user.email", "t@x.dev")
        _git(self.repo, "config", "user.name", "t")
        _git(self.repo, "config", "commit.gpgsign", "false")
        # 0xe9 is 'e-acute' in Latin-1 and is not valid UTF-8 on its own.
        (self.repo / "latin.py").write_bytes(
            b"# caf\xe9 module\ndef price(x):\n    return max(0.0, x)\n"
        )
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "base")
        self.base = _git(self.repo, "rev-parse", "HEAD").stdout.strip()
        (self.repo / "latin.py").write_bytes(
            b"# caf\xe9 module\ndef price(x):\n    return x\n"
        )
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-qm", "head")
        self.head = _git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def test_git_diff_does_not_raise(self):
        text = git_diff(self.repo, self.base, self.head)
        self.assertIsInstance(text, str)
        self.assertIn("latin.py", text)

    def test_git_show_does_not_raise(self):
        text = git_show(self.repo, self.base, "latin.py")
        self.assertIsInstance(text, str)
        self.assertIn("def price", text)

    def test_targets_are_extracted(self):
        text = git_diff(self.repo, self.base, self.head)
        targets = extract_targets(
            text, repo=self.repo, base=self.base, head=self.head
        )
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].symbol, "price")


class TestDecodePolicyIsExplicit(unittest.TestCase):
    """Structural guard: no text-mode subprocess may use the strict default."""

    def test_every_text_subprocess_sets_an_errors_policy(self):
        offenders = []
        for path in sorted(SRC.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            # Look at each subprocess.run/Popen call as a whole expression.
            for match in re.finditer(r"subprocess\.(?:run|Popen)\(", source):
                start = match.end()
                depth, i = 1, start
                while i < len(source) and depth:
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                    i += 1
                call = source[start:i]
                if "text=True" in call and "errors=" not in call:
                    line = source[:match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line}")
        self.assertEqual(
            offenders, [],
            "text-mode subprocess calls without an explicit errors= policy "
            "will crash on repositories containing non-UTF-8 bytes: "
            + ", ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
