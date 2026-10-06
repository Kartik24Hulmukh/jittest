"""Regression tests for the 2026-10-06 smoke-arm repairs.

1. ensure_repo must accept a spec with no pinned revisions (the settled-merge
   pilot samples merge pairs from history; there is no buggy/fixed pair to
   verify). Previously the empty strings were fed to fetch_commit and every
   such clone reported ``commits-missing:,``.
2. eval scripts must not hardcode http_timeout=30 over the documented
   JITTEST_HTTP_TIMEOUT knob and the 300s code default.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from eval.run_bugsinpy import BugSpec, ensure_repo  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_source_repo(root: Path) -> Path:
    src = root / "origin-repo"
    src.mkdir()
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run(["git", "-C", str(src), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    return src


class EnsureRepoEmptyRevisionsTest(unittest.TestCase):
    def test_empty_revisions_mean_nothing_to_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = _make_source_repo(root)
            spec = BugSpec(project="fp-pilot", bug_id="", repo_url=str(src),
                           buggy_commit="", fixed_commit="", test_file="")
            repo, reason = ensure_repo(spec, root / "work")
            self.assertIsNotNone(repo)
            self.assertEqual(reason, "", msg="empty revisions must not report commits-missing")

    def test_missing_pinned_revision_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = _make_source_repo(root)
            spec = BugSpec(project="p", bug_id="1", repo_url=str(src),
                           buggy_commit="0" * 40, fixed_commit="1" * 40, test_file="")
            repo, reason = ensure_repo(spec, root / "work")
            self.assertIsNotNone(repo)
            self.assertTrue(reason.startswith("commits-missing:"), msg=reason)


class EvalTimeoutOverrideTest(unittest.TestCase):
    def test_eval_scripts_do_not_pin_30s_over_the_documented_knob(self):
        for name in ("eval/ga73_measurements.py", "eval/ga73_canary.py",
                     "eval/ga73_pr_pilot.py"):
            text = (REPO_ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("http_timeout=30", text,
                             msg=f"{name} hardcodes http_timeout=30 over JITTEST_HTTP_TIMEOUT")
        # preflight is a deliberate quick probe and keeps its own short timeout
        self.assertIn("http_timeout=15",
                      (REPO_ROOT / "eval/preflight_model.py").read_text(encoding="utf-8"))

    def test_fp_arm_uses_dedicated_runtime_image_env(self):
        """Recent settled-merge heads (Click >=2025) need Python >=3.10 while the
        BugsInPy arm pins a 3.8-era image; the FP arm must read its own pinned
        image from JITTEST_FP_RUNTIME_IMAGE and pass it through config."""
        import inspect

        import eval.ga73_measurements as gm
        src = inspect.getsource(gm.main)
        self.assertIn("JITTEST_FP_RUNTIME_IMAGE", src)
        self.assertIn('"runtime_image": fp_runtime_image', src)
        self.assertIn("fp_runtime_image_is_shared", src)
        # The cfg override alone cannot win: load_runtime_image falls back to the
        # JITTEST_RUNTIME_IMAGE env, which would shadow the override. The FP phase
        # must rebind the env so the modern image actually governs.
        self.assertIn('os.environ["JITTEST_RUNTIME_IMAGE"] = fp_runtime_image', src)

    def test_smoke_workflow_builds_and_uploads_the_fp_image(self):
        text = (REPO_ROOT / ".github" / "workflows" / "ga73-smoke.yml").read_text(encoding="utf-8")
        self.assertIn("python:3.12-slim", text)
        self.assertIn("JITTEST_FP_RUNTIME_IMAGE", text)
        self.assertIn("ga73-fp-runtime-image.txt", text)

    def test_measurements_accepts_fp_repo_url(self):
        import inspect

        import eval.ga73_measurements as gm
        src = inspect.getsource(gm.main)
        self.assertIn("--fp-repo-url", src)
        self.assertIn("fp-pilot", src)


if __name__ == "__main__":
    unittest.main()
