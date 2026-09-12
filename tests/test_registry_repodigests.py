"""Authoritative RepoDigests verification tests (handoff P0-2).

Every adversarial case from the premortem matrix asserts a fail-closed
verdict: unpinned tags, spoofed local Ids, empty RepoDigests, registry
timeouts, digest mismatch and unauthorized mirrors never verify.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.jittest import registry  # noqa: E402

NAME = "docker.io/library/python"
GOOD = "sha256:" + "ab" * 32
OTHER = "sha256:" + "cd" * 32
REF = NAME + "@" + GOOD


def fake_inspector(digests, image_id="", err=""):
    def _probe(backend, image, timeout=30):
        return list(digests), image_id, err
    return _probe


class TestRefValidation(unittest.TestCase):
    def test_unpinned_tag_refused(self):
        ok, reason = registry.validate_image_ref("python:3.12-slim")
        self.assertFalse(ok)
        self.assertIn("unpinned_image_ref", reason)

    def test_uppercase_hex_refused(self):
        ok, _ = registry.validate_image_ref(NAME + "@sha256:" + "AB" * 32)
        self.assertFalse(ok)

    def test_short_digest_refused(self):
        ok, _ = registry.validate_image_ref(NAME + "@sha256:" + "ab" * 31)
        self.assertFalse(ok)

    def test_empty_refused(self):
        ok, _ = registry.validate_image_ref("")
        self.assertFalse(ok)

    def test_pinned_ref_accepted(self):
        ok, reason = registry.validate_image_ref(REF)
        self.assertTrue(ok)
        self.assertEqual(reason, "")


class TestVerifyFailClosed(unittest.TestCase):
    def test_unsupported_backend_refused(self):
        ok, reason, _ = registry.verify_image_digest("none", REF)
        self.assertFalse(ok)
        self.assertIn("unsupported_backend", reason)

    def test_missing_repo_digests_refused(self):
        # A matching local .Id is NOT proof: spoofed retags produce exactly this.
        ok, reason, _ = registry.verify_image_digest(
            "docker", REF, inspector=fake_inspector([], image_id=GOOD)
        )
        self.assertFalse(ok)
        self.assertIn("missing_repo_digests", reason)

    def test_digest_mismatch_refused(self):
        ok, reason, _ = registry.verify_image_digest(
            "docker", REF, inspector=fake_inspector([NAME + "@" + OTHER])
        )
        self.assertFalse(ok)
        self.assertIn("repo_digest_mismatch", reason)

    def test_inspect_failure_fail_closed(self):
        ok, reason, _ = registry.verify_image_digest(
            "docker", REF, inspector=fake_inspector([], err="inspect_failed: registry timeout")
        )
        self.assertFalse(ok)
        self.assertIn("inspect_failed", reason)

    def test_unparsable_inspect_fail_closed(self):
        ok, reason, _ = registry.verify_image_digest(
            "podman", REF, inspector=fake_inspector([], err="inspect_unparsable")
        )
        self.assertFalse(ok)
        self.assertIn("inspect_unparsable", reason)

    def test_authoritative_match_verifies(self):
        ok, reason, digest = registry.verify_image_digest(
            "docker", REF, inspector=fake_inspector([NAME + "@" + GOOD, "mirror.io/python@" + GOOD])
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(digest, GOOD)

    def test_mirror_policy_rejects_unauthorized_registry(self):
        ok, reason, _ = registry.verify_image_digest(
            "docker", REF,
            mirror_policy={NAME: ["registry.example.com"]},
            inspector=fake_inspector(["evil.io/" + NAME.split("/", 1)[1] + "@" + GOOD]),
        )
        self.assertFalse(ok)
        self.assertIn("unauthorized_mirror", reason)

    def test_mirror_policy_allows_listed_registry(self):
        ok, _, _ = registry.verify_image_digest(
            "docker", REF,
            mirror_policy={NAME: ["registry.example.com"]},
            inspector=fake_inspector(["registry.example.com/python@" + GOOD]),
        )
        self.assertTrue(ok)


class TestInspectParsing(unittest.TestCase):
    def test_inspect_rejects_unknown_backend_without_subprocess(self):
        digests, image_id, err = registry.inspect_image_repo_digests("dockerless", REF)
        self.assertEqual(digests, [])
        self.assertIn("unsupported_backend", err)
        self.assertEqual(image_id, "")


if __name__ == "__main__":
    unittest.main()
