"""Regression tests for Defect 28: strict UTF-8 decoding crashed the whole run.

jittest shells out to git and to a test runner constantly. Every one of those
calls used `text=True` with no `errors=` policy, which means Python's strict
UTF-8 decoder. Real repositories are not all UTF-8: a Latin-1 accented name in
a fixture, a copyright header written on Windows in 2011, a byte-order mark, a
CP1252 apostrophe in a docstring. One such byte anywhere in a changed file
raised:

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xe9 in position 115:
    invalid continuation byte

raised inside `subprocess._translate_newlines`, before any jittest code could
run. The tool did not degrade, skip the file, or warn - it crashed. For a tool
whose entire distribution strategy is "add this Action to your repo and it just
works on your next PR", that is a first-run kill.

The policy is now `errors="replace"` everywhere: an undecodable byte becomes a
replacement character in a diff we are reading for structure, which is always
preferable to failing the run.

The last test in this file is structural rather than behavioural. It reads the
source of every shipped module and fails if any text-mode subprocess call omits
an `errors=` policy. Behavioural tests only cover the paths someone thought to
exercise; this one covers the file nobody remembered.
"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "jittest"
sys.path.insert(0, str(SRC.parent))

from jittest.diff import extract_targets, git_diff, git_show  # noqa: E402

# 0xe9 is 'e' with an acute accent in Latin-1 and an invalid UTF-8 lead byte.
LATIN1_COMMENT = b"# author: Jos\xe9 Nu\xf1ez, 2011\n"

BASE_SOURCE = LATIN1_COMMENT + (
    b"def apply_discount(price, percent):\n"
    b"    discounted = price * (1 - percent / 100)\n"
    b"    return max(0.0, discounted)\n"
)

HEAD_SOURCE = LATIN1_COMMENT + (
    b"def apply_discount(price, percent):\n"
    b"    discounted = price * (1 - percent / 100)\n"
    b"    return round(discounted, 2)\n"
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, errors="replace", check=True, timeout=120,
    )


class TestNonUtf8Repository(unittest.TestCase):
    """A repository containing a non-UTF-8 byte must still be analysable."""

    @classmethod
    def setUpClass(cls):
        cls.repo = Path(tempfile.mkdtemp()) / "repo"
        cls.repo.mkdir()
        git(cls.repo, "init", "-q", "-b", "main")
        git(cls.repo, "config", "user.email", "t@example.com")
        git(cls.repo, "config", "user.name", "Test")
        target = cls.repo / "money.py"
        target.write_bytes(BASE_SOURCE)
        git(cls.repo, "add", "-A")
        git(cls.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
        cls.base = git(cls.repo, "rev-parse", "HEAD").stdout.strip()
        target.write_bytes(HEAD_SOURCE)
        git(cls.repo, "add", "-A")
        git(cls.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "head")
        cls.head = git(cls.repo, "rev-parse", "HEAD").stdout.strip()

    def test_git_diff_does_not_raise(self):
        text = git_diff(self.repo, self.base, self.head)
        self.assertTrue(text.strip(), "diff was empty on a real change")
        self.assertIn("money.py", text)

    def test_git_show_does_not_raise(self):
        source = git_show(self.repo, self.base, "money.py")
        self.assertIn("apply_discount", source)

    def test_targets_are_extracted(self):
        text = git_diff(self.repo, self.base, self.head)
        targets = extract_targets(text, repo=self.repo, base=self.base, head=self.head)
        self.assertTrue(targets, "no target found in a non-UTF-8 file")
        self.assertEqual(targets[0].symbol, "apply_discount")


class TestDecodePolicyIsExplicit(unittest.TestCase):
    """Structural guard: no shipped module may use the strict default decoder."""

    def test_every_text_subprocess_sets_an_errors_policy(self):
        offenders = []
        for path in sorted(SRC.glob("*.py")):
            source = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(r"subprocess\.(run|Popen|check_output)\s*\(",
                                     source):
                start = match.end() - 1
                depth = 0
                end = start
                for i in range(start, len(source)):
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                        if depth == 0:
                            end = i
                            break
                call = source[start:end + 1]
                if "text=True" in call and "errors=" not in call:
                    line = source[:match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line}")
        self.assertEqual(
            offenders, [],
            "text-mode subprocess calls without an errors= policy will crash on "
            f"any non-UTF-8 byte: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
