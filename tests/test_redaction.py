"""Defect 65: a secret must not reach a pull-request comment via the excerpt.

Defect 62 stopped a generated test from reading jittest's own credentials.
That closes one route and leaves others open, because the repository under test
has secrets of its own. A candidate that imports the application triggers config
loading and a connection string lands in the traceback; pytest prints locals for
the failing frame, including one named `token`; the application logs an
Authorization header to stderr. All of it flows into RunResult.tail, becomes
Verdict.failure_excerpt, and gets quoted into a public comment.

jittest would then be the thing that published the secret, on behalf of a
repository that was storing it correctly. These tests pin the redaction, and
just as importantly pin that the excerpt is still diagnostically useful
afterwards - redaction that destroys the traceback would simply be traded away
by the first user who needed to debug something.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from jittest.execute import Outcome, RunResult
from jittest.redact import MASK, redact

# Every fixture below is ASSEMBLED at import time rather than written as a
# literal. The reason is not cosmetic.
#
# The first version of this file spelled the tokens out in full. GitHub Push
# Protection rejected the push outright (GH013) because the Slack fixture
# matched its real-token detector - correctly, since a scanner cannot tell a
# convincing fake from the real thing, and that is the entire point of a
# scanner. Worse, the NVIDIA fixture had been copied from a key pasted during
# development, so a real credential prefix was sitting in a test file about
# not leaking credentials. No detector caught that one.
#
# Composing the values keeps the runtime string exactly the right SHAPE, so the
# patterns are still exercised against realistic input, while the bytes stored
# in git match no detector and can never be a real secret. A test suite about
# secret hygiene should not be the thing that trains people to click
# "allow secret".
_PAD = "a" * 40


class TestVendorTokenFormats(unittest.TestCase):
    """Unambiguous formats. The vendor prefix means "this is a credential"."""

    CASES = {
        "nvidia": "nvapi" + "-" + _PAD,
        "openai": "sk" + "-" + _PAD,
        "github_pat": "ghp" + "_" + ("A" * 36),
        "github_fine": "github" + "_pat_" + ("B" * 30),
        "slack": "xox" + "b-" + ("1" * 12) + "-" + ("c" * 16),
        "aws": "AKIA" + ("Z" * 16),
        "google": "AIza" + ("d" * 35),
        "google_oauth": "ya29" + "." + ("e" * 30),
        "jwt": "eyJ" + ("f" * 12) + "." + "eyJ" + ("g" * 12) + "." + ("h" * 20),
    }

    def test_each_vendor_token_is_masked(self):
        for label, token in self.CASES.items():
            with self.subTest(vendor=label):
                out = redact(f"E   assert response.ok, {token}")
                self.assertNotIn(token, out)
                self.assertIn(MASK, out)

    def test_no_fixture_in_this_file_is_a_literal_token(self):
        """Guards the property that made this file safe to commit.

        A future contributor adding a vendor will reach for a realistic-looking
        constant, because that is the obvious thing to do. This fails the build
        instead of failing the push, which is a much cheaper place to find out.
        """
        source = Path(__file__).read_text(encoding="utf-8")
        for token in self.CASES.values():
            self.assertNotIn(token, source,
                             "assembled fixtures must not appear verbatim in "
                             "the source; compose them instead")


class TestCredentialShapedAssignments(unittest.TestCase):
    """The shape that actually leaks in practice."""

    # Composed like the vendor fixtures above: an env-style assignment is the
    # single most-flagged shape in secret scanning (GitGuardian "Generic
    # Password" fired on the literal), and a literal here would train people
    # to click "allow secret". The runtime string is identical either way.
    DB_ASSIGNMENT = "DATABASE_" + "PASSWORD" + "=s3cr3t" + "-value"

    def test_no_fixture_in_this_class_is_a_literal_assignment(self):
        """Same guard as the vendor test, for this class's fixtures."""
        source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn(self.DB_ASSIGNMENT, source,
                         "composed fixtures must not appear verbatim in the "
                         "source; assemble them instead")

    def test_env_style_assignment(self):
        out = redact(self.DB_ASSIGNMENT)
        self.assertNotIn("s3cr3t-value", out)

    def test_dict_repr_from_a_traceback(self):
        out = redact("E   assert config == {'api_key': 'abc123def456'}")
        self.assertNotIn("abc123def456", out)

    def test_python_local_variable_line(self):
        out = redact("token = 'ya29.averylongopaquevalue'")
        self.assertNotIn("averylongopaquevalue", out)

    def test_the_name_survives_so_the_reviewer_knows_what_was_withheld(self):
        # Masking the name too would leave the reviewer unable to tell whether
        # the test failed on a credential or on something else entirely.
        out = redact(self.DB_ASSIGNMENT)
        self.assertIn("DATABASE_PASSWORD", out)

    def test_authorization_header(self):
        out = redact("Authorization: Bearer abcdef0123456789xyz")
        self.assertNotIn("abcdef0123456789xyz", out)
        self.assertIn("Bearer", out)

    def test_connection_string_password_only(self):
        out = redact("postgres://appuser:hunter2@db.internal:5432/prod")
        self.assertNotIn("hunter2", out)
        # The host is the diagnostically useful part and is kept.
        self.assertIn("db.internal", out)

    def test_private_key_block_is_masked_whole(self):
        # Composed, not literal: GitHub Push Protection rejects pushes that
        # contain a private key header followed by a key-shaped body, and it
        # cannot tell this fake from a real one. See the note at the top.
        head = "-----" + "BEGIN RSA PRIVATE" + " KEY-----"
        foot = "-----" + "END RSA PRIVATE" + " KEY-----"
        body = ("M" + "I" * 3 + "owIBAAKCAQEA" + ("x" * 40))
        pem = f"{head}\n{body}\n{body}\n{foot}"
        out = redact(f"stderr:\n{pem}\n")
        self.assertNotIn(body, out)
        self.assertNotIn("BEGIN RSA PRIVATE" + " KEY", out)


class TestRedactionKeepsTheExcerptUseful(unittest.TestCase):
    """Redaction that destroys the traceback would be traded away immediately."""

    def test_ordinary_traceback_is_untouched(self):
        text = ("Traceback (most recent call last):\n"
                '  File "/repo/app/calc.py", line 42, in apply_discount\n'
                "    return round(price * (1 - pct), 2)\n"
                "AssertionError: 90.0 != 89.99\n")
        self.assertEqual(redact(text), text)

    def test_the_failing_assertion_survives(self):
        text = "E   AssertionError: expected 3 items, got 2"
        self.assertEqual(redact(text), text)

    def test_a_variable_named_key_without_a_value_is_untouched(self):
        text = "E   KeyError: 'api_key'"
        self.assertIn("api_key", redact(text))

    def test_empty_and_whitespace_are_safe(self):
        self.assertEqual(redact(""), "")
        self.assertEqual(redact("   "), "   ")

    def test_redaction_is_idempotent(self):
        # The excerpt is truncated and re-quoted in several places; applying
        # the mask twice must not corrupt it.
        once = redact("API_KEY=abc123def456ghi")
        self.assertEqual(redact(once), once)


class TestTailIsTheChokePoint(unittest.TestCase):
    """Every failure_excerpt in the codebase is built from RunResult.tail."""

    def test_tail_redacts_stdout(self):
        r = RunResult(outcome=Outcome.FAIL,
                      stdout="API_KEY=supersecretvalue123", stderr="")
        self.assertNotIn("supersecretvalue123", r.tail)

    def test_tail_redacts_stderr(self):
        r = RunResult(outcome=Outcome.FAIL, stdout="",
                      stderr="nvapi" + "-" + ("b" * 40))
        self.assertNotIn("nvapi" + "-" + ("b" * 40), r.tail)

    def test_tail_still_reports_the_failure(self):
        r = RunResult(outcome=Outcome.FAIL,
                      stdout="AssertionError: 90.0 != 89.99", stderr="")
        self.assertIn("89.99", r.tail)

    def test_a_secret_at_the_truncation_boundary_is_not_half_masked(self):
        # Truncation happens before redaction, so a token cut in half by the
        # 2500-character limit cannot leave a readable fragment behind.
        secret = "nvapi" + "-" + "a" * 40
        r = RunResult(outcome=Outcome.FAIL,
                      stdout=("x" * 3000) + secret, stderr="")
        self.assertNotIn(secret, r.tail)


if __name__ == "__main__":
    unittest.main()
