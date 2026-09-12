"""Dependency-free regressions for fail-closed provisioning boundaries."""
import tempfile
import unittest
from pathlib import Path

from jittest import provision

DIGEST = "sha256:" + "ab" * 32


class Engine:
    def __init__(self, fault=None):
        self.fault = fault
        self.created = []
        self.destroyed = []

    def inspect_repo_digests(self, image):
        if self.fault == "repo_inspect":
            raise ConnectionError("unavailable")
        return ["img@" + DIGEST]

    def inspect_digest(self, image):
        if self.fault == "inspect":
            raise ConnectionError("unavailable")
        return DIGEST

    def create(self, spec):
        self.created.append(spec["phase"])
        return spec["phase"]

    def destroy(self, cid):
        if self.fault == "destroy_" + cid:
            raise OSError("unavailable")
        self.destroyed.append(cid)


class TestProvisionBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "requirements.txt").write_text("demo==1.0", encoding="utf-8")
        self.wh = self.root / "wh"
        self.wh.mkdir()
        (self.wh / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel")
        self.plan = {"image": "img", "image_digest": DIGEST}

    def run_plan(self, engine):
        return provision.provision_in_sandbox(self.root, self.plan, engine, self.wh)

    def test_preflight_errors_are_typed_refusals(self):
        for fault in ("inspect", "repo_inspect"):
            with self.subTest(fault=fault):
                engine = Engine(fault)
                with self.assertRaises(provision.ProvisioningRefusal):
                    self.run_plan(engine)
                self.assertEqual(engine.created, [])

    def test_invalid_plan_and_missing_requirements_are_typed(self):
        for plan in ({}, {"image": "img", "image_digest": 42},
                     {"image": "img", "image_digest": DIGEST, "python": object()},
                     {"image": "img", "image_digest": DIGEST, "requirements": "absent"}):
            with self.subTest(plan=plan):
                self.plan = plan
                engine = Engine()
                with self.assertRaises(provision.ProvisioningRefusal):
                    self.run_plan(engine)
                self.assertEqual(engine.created, [])

    def test_cleanup_errors_are_typed_and_stop_progress(self):
        for phase in ("fetch", "run"):
            with self.subTest(phase=phase):
                engine = Engine("destroy_" + phase)
                with self.assertRaisesRegex(provision.ProvisioningRefusal, "cleanup_failure_" + phase) as ctx:
                    self.run_plan(engine)
                self.assertIsInstance(ctx.exception.__cause__, OSError)
                self.assertEqual(engine.created, ["fetch"] if phase == "fetch" else ["fetch", "run"])

    def test_primary_refusal_survives_cleanup_failure(self):
        for wheel in self.wh.iterdir():
            wheel.unlink()
        engine = Engine("destroy_fetch")
        with self.assertRaisesRegex(provision.ProvisioningRefusal, "wheelhouse_empty") as ctx:
            self.run_plan(engine)
        self.assertTrue(any("cleanup_failure_fetch" in n for n in ctx.exception.__notes__))
        self.assertEqual(engine.created, ["fetch"])

    def test_success_has_exactly_once_cleanup(self):
        engine = Engine()
        manifest = self.run_plan(engine)
        self.assertEqual(engine.created, ["fetch", "run"])
        self.assertEqual(engine.destroyed, ["fetch", "run"])
        self.assertEqual(manifest.network_policy, "none")

    def test_wheel_hashing_never_reads_entire_artifact(self):
        from unittest.mock import patch
        with patch.object(Path, "read_bytes", side_effect=AssertionError("unbounded read")):
            self.assertEqual(len(provision.freeze_wheelhouse(self.wh)), 1)

    def test_seeded_out_of_order_fault_sweep(self):
        import random
        from concurrent.futures import ThreadPoolExecutor, as_completed

        faults = [None, "inspect", "repo_inspect", "destroy_fetch", "destroy_run"]
        jobs = [(i, faults[i % len(faults)]) for i in range(500)]
        random.Random(186).shuffle(jobs)

        def one(job):
            i, fault = job
            engine = Engine(fault)
            try:
                manifest = self.run_plan(engine)
                outcome = manifest.to_dict()
            except provision.ProvisioningRefusal:
                outcome = None
            return i, fault, outcome, engine.created, engine.destroyed

        with ThreadPoolExecutor(max_workers=32) as pool:
            results = [f.result() for f in as_completed([pool.submit(one, job) for job in jobs])]
        accepted = []
        for _, fault, outcome, created, destroyed in sorted(results):
            self.assertEqual(outcome is not None, fault is None)
            if fault is None:
                accepted.append(outcome)
                self.assertEqual(created, destroyed)
            elif fault in ("inspect", "repo_inspect"):
                self.assertEqual(created, [])
            elif fault == "destroy_fetch":
                self.assertEqual(created, ["fetch"])
                self.assertEqual(destroyed, [])  # unresolved cleanup, never claim no leak
            else:
                self.assertEqual(destroyed, ["fetch"])
        self.assertTrue(all(m == accepted[0] for m in accepted))
