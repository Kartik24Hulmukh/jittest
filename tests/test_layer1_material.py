"""Real local Git material regressions; no public acquisition or provider calls."""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_layer1_sweep as sweep


def git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], stderr=subprocess.DEVNULL,
    ).decode().strip()


def fixture(root):
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Owned material fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "app.py").write_text("def value():\n    return 1\n")
    fixed_test = b"from app import value\ndef test_value():\n    assert value() == 1\n"
    (repo / "test_value.py").write_bytes(fixed_test)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "fixed")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "app.py").write_text("def value():\n    return 2\n")
    (repo / "test_value.py").write_text("def test_value():\n    assert True\n")
    git(repo, "commit", "-qam", "buggy")
    head = git(repo, "rev-parse", "HEAD")
    # Never trust even a dirty outer checkout that claims to be on this SHA.
    (repo / "test_value.py").write_text("def test_value():\n    assert False\n")
    row = {"row_id": "owned_material", "kind": "bug", "repository": "owned",
           "base_sha": base, "head_sha": head, "test": "test_value.py",
           "test_source_ref": base}
    return repo, row, fixed_test


class Layer1Material(unittest.TestCase):
    def test_dirty_outer_tip_actual_verifier_and_receipt_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, data = fixture(root)
            outer = (repo / "test_value.py").read_bytes()
            out = root / "evidence"
            out.mkdir()
            with patch.object(sweep, "resolve_fixture_repo", return_value=repo), patch.dict(
                os.environ, {"JITTEST_FORCE_MINIRUNNER": "1",
                             "JITTEST_SIGNING_KEY_PATH": str(root / "signing.pem")},
            ):
                result = sweep.verify_row_task((1, 1, row, out, 10))
            self.assertEqual(result["verdict"], "proven_catch")
            self.assertTrue(result["signature_valid"])
            self.assertEqual(result["test_source_sha"], row["base_sha"])
            self.assertEqual(result["candidate_sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(Path(result["candidate_material"]).read_bytes(), data)
            receipt = json.loads((out / result["artifact"]).read_text())
            self.assertEqual(receipt["provenance"]["test_file_sha256"],
                             result["candidate_sha256"])
            self.assertEqual((repo / "test_value.py").read_bytes(), outer)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), row["head_sha"])
            self.assertEqual(git(repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_concurrent_different_refs_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, data = fixture(root)
            barrier = threading.Barrier(2)

            def collect(ref):
                with sweep.pinned_material(dict(row, test_source_ref=ref), repo, root / "out") as (
                    worktree, candidate, metadata,
                ):
                    barrier.wait(timeout=10)
                    return str(worktree), candidate.read_bytes(), metadata

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(collect, [row["base_sha"], row["head_sha"]]))
            self.assertNotEqual(results[0][0], results[1][0])
            self.assertEqual(results[0][1], data)
            self.assertNotEqual(results[0][1], results[1][1])
            self.assertNotEqual(results[0][2]["candidate_sha256"],
                                results[1][2]["candidate_sha256"])
            self.assertEqual(git(repo, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_missing_ref_and_path_never_use_outer_tip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, _ = fixture(root)
            for update in [{"test_source_ref": "missing-ref"}, {"test": "missing_test.py"}]:
                with self.subTest(update=update), patch.object(
                    sweep, "resolve_fixture_repo", return_value=repo,
                ), patch.object(sweep, "verify_test") as verifier:
                    result = sweep.verify_row_task((1, 1, dict(row, **update), root / "out", 10))
                    self.assertEqual(result["disposition"], "material_unavailable")
                    self.assertIsNone(result["candidate_sha256"])
                    verifier.assert_not_called()
            with patch.object(sweep, "resolve_fixture_repo", return_value=repo), patch.object(
                sweep, "resolve_revision", side_effect=OSError("owned resolver failure"),
            ):
                result = sweep.verify_row_task((1, 1, row, root / "out", 10))
                self.assertEqual(result["disposition"], "material_unavailable")

    def test_ambiguous_direction_refuses_and_explicit_ref_wins(self):
        row = {"kind": "bug"}
        with self.assertRaises(sweep.MaterialUnavailable):
            sweep.test_source_ref(row, "a", "b")
        self.assertEqual(sweep.test_source_ref(dict(row, test_source_ref="c"), "a", "b"), "c")
        with self.assertRaises(sweep.MaterialUnavailable):
            sweep.test_source_ref(dict(row, test_source_ref=None), "a", "b")
        for invalid in (None, "", 7):
            with self.subTest(invalid=invalid), self.assertRaises(sweep.MaterialUnavailable):
                sweep.test_source_ref(row, invalid, "b")

    def test_existing_manifest_direction_contracts(self):
        for rel in ["phase-c-benchmark-manifest.json", "eval/layer1b_manifest.json"]:
            rows = json.loads((sweep.SCRIPT_DIR / rel).read_text())["rows"]
            for row in rows:
                base = row.get("derived_base_sha") or row.get("base_sha")
                head = row.get("derived_head_sha") or row.get("head_sha")
                expected = base if row["kind"] == "bug" else head
                with self.subTest(manifest=rel, row=row["row_id"]):
                    self.assertEqual(sweep.test_source_ref(row, base, head), expected)

    def test_tool_fixture_uses_committed_tool_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, _ = fixture(root)
            tool = root / "tool"
            tool.mkdir()
            path = tool / "tests/fixtures/v0.2_gate/fixture_owned_01.py"
            path.parent.mkdir(parents=True)
            body = b"def test_owned():\n    assert 1 == 1\n"
            path.write_bytes(body)
            git(tool, "init", "-q")
            git(tool, "config", "user.name", "Owned tool fixture")
            git(tool, "config", "user.email", "fixture@example.invalid")
            git(tool, "add", ".")
            git(tool, "commit", "-qm", "fixture")
            tool_sha = git(tool, "rev-parse", "HEAD")
            path.write_text("def test_dirty():\n    assert False\n")
            del row["test"]
            row["row_id"] = "bug_owned_01"
            for deleted in (False, True):
                if deleted:
                    path.unlink()
                with self.subTest(deleted=deleted), patch.object(
                    sweep, "SCRIPT_DIR", tool,
                ), sweep.pinned_material(row, repo, root / "out") as (_, selected, metadata):
                    self.assertEqual(selected.read_bytes(), body)
                    self.assertEqual(metadata["test_source_sha"], tool_sha)
                    self.assertEqual(metadata["candidate_origin"], "tool_fixture")
                    self.assertEqual(metadata["tool_fixture_sha256"], hashlib.sha256(body).hexdigest())

    def test_candidate_escape_and_receipt_mismatch_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, _ = fixture(root)
            with self.assertRaises(sweep.MaterialUnavailable), sweep.pinned_material(
                dict(row, test="../outside.py"), repo, root / "out",
            ):
                self.fail("escaped candidate accepted")
            with patch.object(sweep, "resolve_fixture_repo", return_value=repo), patch.object(
                sweep, "verify_test", return_value=({"provenance": {"test_file_sha256": "wrong"}}, 0),
            ):
                result = sweep.verify_row_task((1, 1, row, root / "out", 10))
                self.assertEqual(result["disposition"], "material_unavailable")
                self.assertIsNotNone(result["candidate_sha256"])

    def test_duplicate_and_unsafe_row_ids_refuse_before_dispatch(self):
        with self.assertRaises(sweep.MaterialUnavailable):
            sweep.validate_rows([{"row_id": "same"}, {"row_id": "same"}])
        for unsafe in ["../escape", "/absolute", "a/b", "", None]:
            with self.subTest(unsafe=unsafe), self.assertRaises(sweep.MaterialUnavailable):
                sweep.validate_rows([{"row_id": unsafe}])
        sweep.validate_rows([{"row_id": "bug_01"}, {"row_id": "control-02"}])

    def test_actual_persisted_receipt_revisions_must_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, data = fixture(root)
            digest = hashlib.sha256(data).hexdigest()
            out = root / "out"
            out.mkdir()

            def replaced_receipt(**kwargs):
                evidence = {"provenance": {"test_file_sha256": digest,
                                          "base_sha": "wrong", "head_sha": row["head_sha"]}}
                kwargs["output_path"].write_text(json.dumps(evidence))
                return {"provenance": {"test_file_sha256": digest}}, 0

            with patch.object(sweep, "resolve_fixture_repo", return_value=repo), patch.object(
                sweep, "verify_test", side_effect=replaced_receipt,
            ):
                result = sweep.verify_row_task((1, 1, row, out, 10))
                self.assertEqual(result["disposition"], "material_unavailable")
                self.assertEqual(result["candidate_sha256"], digest)

    def test_autocrlf_true_preserves_committed_lf_blob(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, body = fixture(root)
            git(repo, "config", "core.autocrlf", "true")
            outer = (repo / "test_value.py").read_bytes()
            with sweep.Worktree(repo, row["base_sha"]) as checkout:
                self.assertEqual((checkout / "test_value.py").read_bytes(),
                                 body.replace(b"\n", b"\r\n"))
            with sweep.pinned_material(row, repo, root / "out") as (_, selected, metadata):
                self.assertEqual(selected.read_bytes(), body)
                self.assertEqual(metadata["raw_git_blob_sha256"], hashlib.sha256(body).hexdigest())
                self.assertEqual(Path(metadata["candidate_material"]).read_bytes(), body)
            self.assertEqual((repo / "test_value.py").read_bytes(), outer)

    def test_autocrlf_true_preserves_actual_committed_crlf_blob(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, body = fixture(root)
            git(repo, "config", "core.autocrlf", "true")
            crlf = body.replace(b"\n", b"\r\n")
            (repo / ".gitattributes").write_bytes(b"test_value.py -text\n")
            (repo / "test_value.py").write_bytes(crlf)
            (repo / "app.py").write_bytes(b"def value():\n    return 1\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "actual CRLF source blob")
            row["base_sha"] = row["test_source_ref"] = git(repo, "rev-parse", "HEAD")
            stored = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{row['base_sha']}:test_value.py"],
            )
            self.assertEqual(stored, crlf)
            (repo / "app.py").write_bytes(b"def value():\n    return 2\n")
            git(repo, "commit", "-qam", "buggy with CRLF candidate")
            row["head_sha"] = git(repo, "rev-parse", "HEAD")
            (repo / "test_value.py").write_bytes(b"def test_dirty():\n    assert False\n")
            outer = (repo / "test_value.py").read_bytes()
            out = root / "out"
            out.mkdir()
            with patch.object(sweep, "resolve_fixture_repo", return_value=repo), patch.dict(
                os.environ, {"JITTEST_FORCE_MINIRUNNER": "1",
                             "JITTEST_SIGNING_KEY_PATH": str(root / "signing.pem")},
            ):
                result = sweep.verify_row_task((1, 1, row, out, 10))
            self.assertEqual(result["verdict"], "proven_catch")
            self.assertEqual(result["raw_git_blob_sha256"], hashlib.sha256(crlf).hexdigest())
            self.assertEqual(Path(result["candidate_material"]).read_bytes(), crlf)
            receipt = json.loads((out / result["artifact"]).read_text())
            self.assertEqual(receipt["provenance"]["test_file_sha256"], result["candidate_sha256"])
            self.assertEqual((repo / "test_value.py").read_bytes(), outer)

    def test_committed_symlink_refuses_even_without_filesystem_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo, row, _ = fixture(root)
            git(repo, "config", "core.symlinks", "false")
            oid = subprocess.check_output(
                ["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"app.py",
            ).decode().strip()
            git(repo, "update-index", "--cacheinfo", f"120000,{oid},test_value.py")
            git(repo, "commit", "-qm", "owned committed symlink")
            row["test_source_ref"] = git(repo, "rev-parse", "HEAD")
            with self.assertRaises(sweep.MaterialUnavailable), sweep.pinned_material(
                row, repo, root / "out",
            ):
                self.fail("committed symlink accepted as a candidate source")


if __name__ == "__main__":
    unittest.main()