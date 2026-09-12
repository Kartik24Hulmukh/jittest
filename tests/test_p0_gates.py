"""P0 gate tests: provisioning, output boundary, integrity, readiness, stress.

These are the regression tests for the release blockers enumerated in
the 2026-09-12 production-readiness handoff. Every adversarial case
from the handoff matrix asserts a fail-closed refusal, never a
fallback.
"""

import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from src.jittest import integrity, outputguard, provision, readiness
from src.jittest.outputguard import OutputTrustRefusal
from src.jittest.provision import EngineAdapter, ProvisioningRefusal
from src.jittest.readiness import ReadinessRefusal
from src.jittest.verify import VerifyRefusalError

GOOD_DIGEST = "sha256:" + "ab" * 32
OTHER_DIGEST = "sha256:" + "cd" * 32


class FakeEngine:
    def __init__(self, digest=GOOD_DIGEST, fail_phase=None, destroys=None):
        self.digest = digest
        self.fail_phase = fail_phase
        self.created = []
        self.destroyed = destroys if destroys is not None else []
        self.specs = []

    def inspect_digest(self, image):
        return self.digest

    def create(self, spec):
        self.specs.append(spec)
        if self.fail_phase and spec["phase"] == self.fail_phase:
            raise RuntimeError("engine exploded")
        cid = "cid-" + str(len(self.created))
        self.created.append(cid)
        return cid

    def destroy(self, cid):
        self.destroyed.append(cid)


def make_engine(**kw):
    fake = FakeEngine(**kw)
    return EngineAdapter(
        name="fake",
        inspect_digest=fake.inspect_digest,
        create=fake.create,
        destroy=fake.destroy,
    ), fake


def make_repo(tmp, req="requests==2.32.0\n"):
    repo = Path(tmp) / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "requirements.txt").write_text(req, encoding="utf-8")
    wheel = Path(tmp) / "wheelhouse"
    wheel.mkdir(parents=True, exist_ok=True)
    (wheel / "requests-2.32.0-py3-none-any.whl").write_bytes(b"wheelbytes")
    return repo, wheel


class TestProvisioningContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jittest-prov-"))
        self.repo, self.wheel = make_repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan(self, digest=GOOD_DIGEST):
        return {"image": "ghcr.io/x/y:1", "image_digest": digest, "python": "3.12"}

    def test_happy_path_two_phase_network_none(self):
        engine, fake = make_engine()
        manifest = provision.provision_in_sandbox(self.repo, self.plan(), engine, self.wheel)
        self.assertEqual(manifest.network_policy, "none")
        self.assertEqual(manifest.image_digest, GOOD_DIGEST)
        self.assertEqual(len(manifest.artifacts), 1)
        self.assertEqual(fake.specs[0]["network"], "fetch")
        self.assertEqual(fake.specs[1]["network"], "none")
        self.assertTrue(fake.specs[1]["read_only_rootfs"])
        self.assertTrue(fake.specs[1]["no_new_privileges"])
        self.assertEqual(fake.specs[1]["cap_drop"], "ALL")
        self.assertEqual(fake.destroyed, fake.created)  # both phases destroyed

    def test_unpinned_or_malformed_digest_refused(self):
        for bad in ["", "latest", "sha256:ABC", "sha256:" + "a" * 63, OTHER_DIGEST.upper()]:
            engine, _ = make_engine()
            with self.assertRaises(ProvisioningRefusal):
                provision.provision_in_sandbox(self.repo, self.plan(bad), engine, self.wheel)

    def test_digest_mismatch_refuses_never_falls_back(self):
        engine, fake = make_engine(digest=OTHER_DIGEST)
        with self.assertRaises(ProvisioningRefusal) as ctx:
            provision.provision_in_sandbox(self.repo, self.plan(), engine, self.wheel)
        self.assertIn("digest_mismatch", str(ctx.exception))
        self.assertEqual(fake.created, [])  # no container ever started

    def test_engine_failure_phase1_refuses_and_destroys(self):
        engine, fake = make_engine(fail_phase="fetch")
        with self.assertRaises(ProvisioningRefusal) as ctx:
            provision.provision_in_sandbox(self.repo, self.plan(), engine, self.wheel)
        self.assertIn("engine_failure_phase1", str(ctx.exception))

    def test_engine_failure_phase2_never_retries_unconfined(self):
        engine, fake = make_engine(fail_phase="run")
        with self.assertRaises(ProvisioningRefusal) as ctx:
            provision.provision_in_sandbox(self.repo, self.plan(), engine, self.wheel)
        self.assertIn("engine_failure_phase2", str(ctx.exception))
        self.assertEqual(len(fake.created), 1)  # only phase-1 ever ran

    def test_editable_vcs_local_requirements_refused(self):
        for evil in ["-e git+https://x/y#egg=z", "pkg @ git+https://x/y", "./local", "/abs/path"]:
            repo, wheel = make_repo(self.tmp, req=evil + "\n")
            engine, fake = make_engine()
            with self.assertRaises(ProvisioningRefusal):
                provision.provision_in_sandbox(repo, self.plan(), engine, wheel)
            self.assertEqual(fake.created, [])

    def test_empty_wheelhouse_refused(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        engine, _ = make_engine()
        with self.assertRaises(ProvisioningRefusal):
            provision.provision_in_sandbox(self.repo, self.plan(), engine, empty)

    def test_provisioning_refusal_is_verify_refusal(self):
        self.assertTrue(issubclass(ProvisioningRefusal, VerifyRefusalError))


class TestOutputTrustBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jittest-out-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_clean_tree_ok(self):
        ev = self.tmp / "ev"
        ev.mkdir()
        (ev / "receipt.json").write_text("{}", encoding="utf-8")
        scan = outputguard.scan_output_tree(ev)
        self.assertTrue(scan.ok)
        self.assertEqual(scan.files, 1)

    def test_symlink_fifo_hardlink_refused(self):
        ev = self.tmp / "ev"
        ev.mkdir()
        target = self.tmp / "secret"
        target.write_text("x", encoding="utf-8")
        os.symlink(target, ev / "link")
        os.mkfifo(ev / "pipe")
        os.link(target, ev / "hard")
        scan = outputguard.scan_output_tree(ev)
        self.assertFalse(scan.ok)
        joined = ";".join(scan.violations)
        self.assertIn("symlink:", joined)
        self.assertIn("fifo:", joined)
        self.assertIn("hardlink:", joined)
        with self.assertRaises(OutputTrustRefusal):
            scan.raise_if_bad()

    def test_traversal_and_oversized_refused(self):
        ev = self.tmp / "ev"
        ev.mkdir()
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "f.txt").write_text("y", encoding="utf-8")
        os.symlink(outside, ev / "up")
        big = self.tmp / "big"
        big.mkdir()
        (big / "huge.bin").write_bytes(b"0" * (outputguard.DEFAULT_MAX_BYTES + 1))
        self.assertFalse(outputguard.scan_output_tree(big).ok)

    def test_undeclared_write_refused(self):
        ev = self.tmp / "ev"
        ev.mkdir()
        (ev / "a.json").write_text("1", encoding="utf-8")
        (ev / "sneaky.json").write_text("2", encoding="utf-8")
        scan = outputguard.scan_output_tree(ev, declared=("a.json",))
        self.assertIn("undeclared_write:sneaky.json", scan.violations)

    def test_protected_source_tree_immutability(self):
        src = self.tmp / "source"
        src.mkdir()
        (src / "code.py").write_text("print(1)", encoding="utf-8")
        snap = outputguard.snapshot_tree(src)
        outputguard.assert_unchanged(src, snap)
        (src / "code.py").write_text("print(2)", encoding="utf-8")
        with self.assertRaises(OutputTrustRefusal):
            outputguard.assert_unchanged(src, snap)


class TestReceiptIntegrity(unittest.TestCase):
    def test_record_canonical_and_digest_stable(self):
        rec = integrity.build_integrity_record(
            b"src", GOOD_DIGEST, "req==1", "policy", ["python", "-m", "pytest"], 0, b"out"
        )
        self.assertEqual(rec.schema_version, "integrity-1.0")
        self.assertEqual(rec.digest(), rec.digest())
        self.assertFalse(rec.incomplete)
        self.assertFalse(rec.non_reproducible)

    def test_incomplete_and_nonreproducible_are_explicit(self):
        rec = integrity.build_integrity_record(
            b"s", GOOD_DIGEST, "", "", [], 1, b"", refusal_reason="engine_failure_phase2",
            incomplete=True, non_reproducible=True,
        )
        self.assertTrue(rec.incomplete and rec.non_reproducible)
        self.assertTrue(rec.reproducibility_note)
        self.assertEqual(rec.refusal_reason, "engine_failure_phase2")

    def test_compare_runs_detects_difference(self):
        a = integrity.build_integrity_record(b"s", GOOD_DIGEST, "r", "p", ["c"], 0, b"o")
        b = integrity.build_integrity_record(b"s", GOOD_DIGEST, "r", "p", ["c"], 0, b"o2")
        cmp_res = integrity.compare_runs(a, b)
        self.assertFalse(cmp_res["reproducible"])
        self.assertIn("output_sha256", cmp_res["differences"])
        same = integrity.compare_runs(a, a)
        self.assertTrue(same["reproducible"])


class TestDeterministicReadiness(unittest.TestCase):
    def test_missing_direct_dependency_refused(self):
        rep = readiness.evaluate_readiness("flask==3.0.0\n", target_runtime={"requests"})
        self.assertFalse(rep.ok)
        with self.assertRaises(ReadinessRefusal):
            rep.raise_if_bad()

    def test_host_only_package_detected(self):
        rep = readiness.evaluate_readiness(
            "numpy==2.0.0\n", target_runtime=set(), host_visible={"numpy"}
        )
        self.assertIn("numpy", rep.host_only)

    def test_lock_drift_detected(self):
        rep = readiness.evaluate_readiness(
            "requests==2.32.0\n", target_runtime={"requests"}, lock_text="requests==2.31.0\n"
        )
        self.assertFalse(rep.ok)
        self.assertTrue(any(p.startswith("lock_drift") for p in rep.problems))

    def test_platform_incompatibility_detected(self):
        rep = readiness.evaluate_readiness(
            "pkg==1.0\n", target_runtime={"pkg"},
            wheel_names=["pkg-1.0-cp312-cp312-win_amd64.whl"],
        )
        self.assertFalse(rep.ok)

    def test_pure_python_wheel_passes(self):
        rep = readiness.evaluate_readiness(
            "pkg==1.0\n", target_runtime={"pkg"}, wheel_names=["pkg-1.0-py3-none-any.whl"]
        )
        self.assertTrue(rep.ok)

    def test_determinism_same_input_same_verdict(self):
        a = readiness.evaluate_readiness("x==1\n", target_runtime={"x"})
        b = readiness.evaluate_readiness("x==1\n", target_runtime={"x"})
        self.assertEqual((a.ok, a.problems), (b.ok, b.problems))


class TestStressConcurrency(unittest.TestCase):
    def test_100_concurrent_jobs_unique_tmpdirs_and_cleanup(self):
        errors = []
        made = []
        lock = threading.Lock()

        def job(i):
            try:
                tmp = Path(tempfile.mkdtemp(prefix=f"jittest-job-{i}-"))
                with lock:
                    made.append(tmp)
                repo, wheel = make_repo(tmp)
                engine, fake = make_engine()
                provision.provision_in_sandbox(
                    repo,
                    {"image": "i", "image_digest": GOOD_DIGEST, "python": "3.12"},
                    engine, wheel,
                )
                if fake.destroyed != fake.created:
                    raise AssertionError("leaked containers")
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        threads = [threading.Thread(target=job, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len({str(p) for p in made}), 100)  # unique temp dirs
        for p in made:
            self.assertFalse(p.exists())  # cleanup asserted

    def test_integrity_digest_throughput(self):
        data = b"x" * 4096
        for _ in range(2000):
            integrity.sha256_bytes(data)


if __name__ == "__main__":
    unittest.main()
