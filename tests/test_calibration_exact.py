"""Exact 40-character SHA calibration guard test suite for jittest (R2A)."""

import hashlib
import re
import unittest
from pathlib import Path

# Base and head 40-character commit SHAs for W1-R6 benchmark pairs
W1R6_COMMITS = [
    ("27be93389025e11bb2643a6d4ee2796e6d1c9ad9", "c17f37936a297fc95e63df56fd648c69f21d3f66"),
    ("eb58d86237dd7143f2ed970c6eb3f2d22b271d49", "eca5fd1d9165dcfd208940866efc4ff6c0ef6dc3"),
    ("d98eb69a98efae39bd4eddd9e605d398f5a65c40", "f00ad424b96b2fa90b9b3aaecda7925e07662c16"),
    ("20330ff2a7e78ecfa6f7bd0cb14ee1cbcf1ee0c7", "95e0c5d5e54d8fc22ceb1dbbfad8688463138b15"),
    ("eec3081e7d2b7811feec96ab427027d142d7bf3b", "5aa8ebc8ee8eb0059e6ed18cfce11c97a48dbeeb"),
    ("c0d38102a0a2dfcaeddb39cdaeed0ecae5fbfe0e", "4e444dc9ce6d05f33d7eb3d3bfe38aebffcce4ad"),
    ("756ef26e792e342738411d332d73fa9bf1c1ca75", "1c28c89b8be880eb4c718a36ed42ddfa36acfa63"),
    ("ae2aa144f83b6faadce21f7c22998a444cd342bc", "72ca8edcf284bf782cfa23467b738e4a770051ed"),
    ("f6ea605b9b775fd3ea3d2f95fb3ae659b489d81d", "47dca959cfbd4487b415a77f98eeff93630f9a21"),
    ("9be7622dcf1cf3ef3ce7b22a00c6d5952fef40d4", "380b2a758546b5417ae41dfb37cff9d71c4c1d68"),
    ("5cfa1033bfd8e96bfbcbc88981fddacfb00e008a", "0b904dfebca9aa2ebaccc62f43cfdc44c9b31dbe"),
    ("e6ee158dca96b6b772c72472d02c813d11b22e1b", "bb9a98ef1ca50d4f5f59080e72bd58fb2ff8a6db"),
    ("2883015a5ca2bf2e441fe97171e21b7fcf71d884", "0c78aee3a9ddfc3ae6526154b0eb14b51c14fb25"),
    ("9df21a1ca607fcfa3d7aefecbfaebaa7fe7ad1fb", "baad5ddcd91f0eb9dd36b4a62174ea6d123ee3a6"),
    ("49a4639be9b22a969fba75c58a69e320f7871fa1", "fb0ae234ff60b64beaf7c52caef1fa5d83637bc3"),
    ("ebdf9e51c89fbf0e85f02bc9230559eb4cb6801a", "bbf6b146445f1b1a78d052b61ef0a5ddaa83d47d"),
    ("d09dc744b8ee767471676cbafcf0ceebec45bbbc", "ea6314f32c918ef68c85aeaa7bfbcadbb53860bb"),
    ("bd0db6d73507d4b47eb79bd5df375cfefd0979bf", "5512b4859a72dfef6f366aa9e5eb2d1f7362df5a"),
    ("10aa75d40cb9721798cebd33a39e8020ec326e1a", "a6e2e5052fb58f9d0c649fa0278783fb79697fca"),
    ("131885ff39665bcfe9680373fa6c888d374465d2", "3d0bf2eb7eeab0dfbf67c3ed0e39ee4c32ae15be"),
]

SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ExactCalibrationGuardTests(unittest.TestCase):
    def test_calibration_artifact_and_sidecar_exact_match(self):
        """Verify calibration artifact and sidecar file exact SHA-256 digest match."""
        root = Path(__file__).resolve().parent.parent
        artifact_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json"
        sidecar_path = root / "eval" / "artifacts" / "flask-fp-ladder-w1r6-sanitized.json.sha256"

        self.assertTrue(artifact_path.exists(), f"Artifact missing at {artifact_path}")
        self.assertTrue(sidecar_path.exists(), f"Sidecar missing at {sidecar_path}")

        # Compute SHA-256 with normalized LF line endings for cross-platform stability
        text_content = artifact_path.read_text(encoding="utf-8").replace("\r\n", "\n")
        actual_sha = hashlib.sha256(text_content.encode("utf-8")).hexdigest()
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


if __name__ == "__main__":
    unittest.main()
