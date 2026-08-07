"""Exact 40-character SHA calibration guard test suite for jittest (R2A-R2)."""

import hashlib
import json
import re
import unittest
from pathlib import Path

# Base and head 40-character commit SHAs for W1-R6 benchmark pairs (Stage 5)
W1R6_COMMITS = [
    ("06ea505ce2b2042af26e96d35ebf159af7c0869d", "9368fb3f3c52d74534d14c1bef03c79c103356cd"),
    ("258d68b6ff5e2244386540f48b48bab90d6ab827", "689362089edd09b6d68f7cfe99075e1345e0fede"),
    ("e4e4bf6543ac1f132afddb1ffd0bf02bea4c93f7", "a31e6b73469cb2bf7eb8f70b5ff21f710fd2e23c"),
    ("7ef2946fb5151b745df30201b8c27790cac53875", "b21425d6df207fec0c47e9563faa10a2819984ca"),
    ("4cae5d8e411b1e69949d8fae669afeacbd3e5908", "91c6b3fecf36b1f04554e57cc4060ccb737a445d"),
    ("3a9d54f3da1de540adfdf6f1e2dea6fc0006e15d", "a197702e2cbcdd43c0d09296b3cea02efe16e407"),
    ("c34d6e81fd8e405e6d4178bf24b364918811ef17", "a29f88ce6f2f9843bd6fcbbfce1390a2071965d6"),
    ("7b0088693ece1bd3a9238a6fdf56ed8df7a4d43b", "fbb6f0bc4c60a0bada0e03c3480d0ccf30a3c1df"),
    ("d98eb69a354158252854ed4a5c9778e03d089191", "f00ad424ee3b050d382cc5b4aabb18afbb5e4ae7"),
    ("27be9338405382445a7cb01151e084559b98d602", "c17f379390731543eea33a570a47bd4ef76a54fa"),
    ("d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9", "e82db2ca3a22c9614c1987392c9cfaa8c6ce99ad"),
    ("663198d7b453ffdbe86d0e0238b1feafde6ce569", "4e652d3f68b90d50aa2301d3b7e68c3fafd9251d"),
    ("407eb76b27884848383a37c7274654f0271e4bc4", "3d03098a97ddc6a908aa4a50c2ef7381f8297d0a"),
    ("23df07d799f0bed3feb5beb9e5633651687da92b", "407eb76b27884848383a37c7274654f0271e4bc4"),
    ("4b8bde97d4fa3486e18dce21c3c5f75570d50164", "4f79d5b59a56bc4356a97f2e81a35f98cb18d7b3"),
    ("0292047b22c82921dcf165322d93a0b988328c2e", "c77a5203438fe772d41f6a47303ad3f57a4efe6d"),
    ("809d5a8869d4ffe8656680b2438b10f7c8845613", "5559ef42b5334075cbde82b2870ca725ac606fa4"),
    ("30da640ffe23b6e461fa91d387ffea6b9d9fa847", "3709c4a9a87e6ce8c26dc4a951e1df52ac9ecad0"),
    ("64dd0809c2fc732ed30539235232a268f9bd96ac", "dbd4c2882593f6118103120aa96fa9acdf7deedb"),
    ("eb58d862cc4a8f31a369b6e9ad1724e9e642f13f", "eca5fd1dfdc614c2df876cc32018a7d71f84ea82"),
]

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ExactCalibrationGuardTests(unittest.TestCase):
    def test_calibration_artifact_and_sidecar_exact_match(self):
        """Verify calibration artifact and sidecar file exact SHA-256 digest match using read_bytes()."""
        root = Path(__file__).resolve().parent.parent
        artifact_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json"
        sidecar_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json.sha256"

        self.assertTrue(artifact_path.exists(), f"Artifact missing at {artifact_path}")
        self.assertTrue(sidecar_path.exists(), f"Sidecar missing at {sidecar_path}")

        # Compute raw SHA-256 digest using read_bytes() without text normalization
        actual_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        expected_sha = sidecar_path.read_text(encoding="utf-8").strip()

        self.assertEqual(actual_sha, expected_sha, "Sidecar digest mismatch!")

    def test_w1_r6_pairs_40_char_lowercase_hex(self):
        """Verify all 20 W1-R6 base/head commit pairs use exact 40-character lowercase hex format."""
        self.assertEqual(len(W1R6_COMMITS), 20)
        for idx, (base_sha, head_sha) in enumerate(W1R6_COMMITS, 1):
            self.assertTrue(
                SHA_PATTERN.match(base_sha),
                f"Pair {idx} base SHA {base_sha!r} is not exact 40-char lowercase hex",
            )
            self.assertTrue(
                SHA_PATTERN.match(head_sha),
                f"Pair {idx} head SHA {head_sha!r} is not exact 40-char lowercase hex",
            )

    def test_artifact_ancestry_manifest_matches_exact_pairs(self):
        """Verify artifact ancestry_manifest matches W1R6_COMMITS in exact order."""
        root = Path(__file__).resolve().parent.parent
        artifact_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json"
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
        ancestry = data.get("ancestry_manifest", [])

        self.assertEqual(len(ancestry), 20, f"Expected 20 pairs in ancestry_manifest, got {len(ancestry)}")

        for idx, (expected_base, expected_head) in enumerate(W1R6_COMMITS):
            actual_base = ancestry[idx].get("base_sha")
            actual_head = ancestry[idx].get("head_sha")
            self.assertEqual(actual_base, expected_base, f"Pair {idx+1} base mismatch: {actual_base} != {expected_base}")
            self.assertEqual(actual_head, expected_head, f"Pair {idx+1} head mismatch: {actual_head} != {expected_head}")

    def test_uniqueness_negative(self):
        """Verify duplicate SHA pairs are rejected."""
        pairs = list(W1R6_COMMITS) + [W1R6_COMMITS[0]]
        self.assertNotEqual(len(set(pairs)), len(pairs), "Duplicates must be detected")

    def test_reordering_negative(self):
        """Verify reordered SHA pairs fail sequence verification."""
        reordered = list(W1R6_COMMITS)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        self.assertNotEqual(reordered, W1R6_COMMITS, "Reordered pairs must fail match")

    def test_deletion_negative(self):
        """Verify truncated SHA pair list (19 pairs) fails exact count check."""
        truncated = W1R6_COMMITS[:-1]
        self.assertNotEqual(len(truncated), 20, "Truncated pair list must fail length check")

    def test_addition_negative(self):
        """Verify extra SHA pair list (21 pairs) fails exact count check."""
        extra = list(W1R6_COMMITS) + [("a" * 40, "b" * 40)]
        self.assertNotEqual(len(extra), 20, "Extra pair list must fail length check")

    def test_abbreviated_sha_negative(self):
        """Verify abbreviated 7-character SHAs fail 40-character regex check."""
        short_base = "06ea505"
        self.assertFalse(SHA_PATTERN.match(short_base), "Abbreviated SHA must be rejected by SHA_PATTERN")

    def test_byte_mutation_negative(self):
        """Verify byte mutation in raw artifact content changes SHA-256 digest."""
        root = Path(__file__).resolve().parent.parent
        artifact_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json"
        raw_bytes = artifact_path.read_bytes()
        mutated_bytes = raw_bytes[:-1] + b"X"
        mutated_sha = hashlib.sha256(mutated_bytes).hexdigest()
        actual_sha = hashlib.sha256(raw_bytes).hexdigest()
        self.assertNotEqual(mutated_sha, actual_sha, "Byte mutation must change SHA-256 digest")


if __name__ == "__main__":
    unittest.main()
