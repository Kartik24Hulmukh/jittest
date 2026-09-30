"""Release ordering, evidence preservation and source-byte regressions."""
import importlib.util
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAcceptanceContract(unittest.TestCase):
    def test_failed_verification_still_uploads_evidence(self):
        text = (ROOT / "action.yml").read_text()
        step = text.split("- name: Upload evidence artifacts", 1)[1]
        self.assertIn("if: always()", step)

    def test_floating_tag_waits_for_registry_and_github_release(self):
        text = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("needs: [verify-published, github-release]", text)
        self.assertIn("check_distributable.py --dist dist", text)
        self.assertIn("check_published_bytes.py --dist dist", text)
        self.assertIn("pip install -q '.[dev,melious]'", text)

    def test_packaged_source_missing_or_modified_fails(self):
        spec = importlib.util.spec_from_file_location("distributable", ROOT / "scripts/check_distributable.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src/jittest").mkdir(parents=True)
            # The contract is byte equality, not platform text newline equality.
            (root / "src/jittest/__init__.py").write_bytes(b"version = '1'\n")
            wheel = root / "example.whl"
            for content in ("version = '1'\n", "changed", None):
                with zipfile.ZipFile(wheel, "w") as archive:
                    if content is not None:
                        archive.writestr("jittest/__init__.py", content)
                if content == "version = '1'\n":
                    self.assertEqual(len(module.reconcile(wheel, root)), 1)
                else:
                    with self.assertRaises(ValueError):
                        module.reconcile(wheel, root)