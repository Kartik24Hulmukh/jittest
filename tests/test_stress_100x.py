"""Wave-100x stress battery (2026-09-12 round 3).

Everything here runs the public fail-closed seams at 100x parallelism
and asserts the *invariants*, not just happy-path success:
deterministic manifests, zero leaked containers, refusal storms,
between-phase digest drift, canonical integrity digests and a
zero-false-accept output-guard scan.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError as exc:  # dependency-free unittest discovery
    import unittest

    raise unittest.SkipTest("requires pytest; exercised by the pytest CI lane") from exc

from jittest import integrity, outputguard, provision, readiness

DIGEST = "sha256:" + "ab" * 32
DRIFTED = "sha256:" + "cd" * 32


class FakeEngine:
    """Scriptable engine: records lifecycle, never silently passes."""

    def __init__(self, digest: str = DIGEST, repo_digests: list[str] | None = None):
        self.digest = digest
        self.repo_digests = repo_digests if repo_digests is not None else ["img@" + DIGEST]
        self.created: list[dict] = []
        self.destroyed: list[str] = []

    def inspect_digest(self, image: str) -> str:
        return self.digest

    def inspect_repo_digests(self, image: str):
        return list(self.repo_digests)

    def create(self, spec: dict) -> str:
        self.created.append(spec)
        return f"ctr-{len(self.created)}"

    def destroy(self, cid: str) -> None:
        self.destroyed.append(cid)


def _wheelhouse(tmp: Path, n: int = 2) -> Path:
    wh = tmp / "wheelhouse"
    wh.mkdir()
    for i in range(n):
        (wh / f"demo-{i}.0-py3-none-any.whl").write_bytes(f"wheel-{i}".encode())
    return wh


def _repo(tmp: Path, reqs: str = "demo==1.0\n") -> Path:
    (tmp / "requirements.txt").write_text(reqs, encoding="utf-8")
    return tmp


def _plan() -> dict:
    return {"image": "img", "image_digest": DIGEST, "python": "3.12"}


def test_200_parallel_provisioning_byte_identical_manifests(tmp_path: Path) -> None:
    def one(i: int):
        root = tmp_path / f"job{i}"
        root.mkdir()
        engine = FakeEngine()
        manifest = provision.provision_in_sandbox(
            _repo(root), _plan(), engine, _wheelhouse(root)
        )
        return manifest, engine

    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(one, range(200)))

    canonical = {
        json.dumps(m.to_dict(), sort_keys=True) for m, _ in results
    }
    assert len(canonical) == 1, "manifests must be byte-identical across 200 jobs"
    for _, engine in results:
        assert len(engine.created) == 2
        assert sorted(engine.destroyed) == ["ctr-1", "ctr-2"], "no container may leak"
        assert engine.created[1]["network"] == "none"
        assert engine.created[1]["read_only_rootfs"] is True
        assert engine.created[1]["cap_drop"] == "ALL"


def test_200_job_refusal_storm_never_creates_containers(tmp_path: Path) -> None:
    def one(i: int):
        root = tmp_path / f"job{i}"
        root.mkdir()
        engine = FakeEngine(repo_digests=["img@" + DRIFTED])
        with pytest.raises(provision.ProvisioningRefusal):
            provision.provision_in_sandbox(_repo(root), _plan(), engine, _wheelhouse(root))
        return engine

    with ThreadPoolExecutor(max_workers=32) as pool:
        engines = list(pool.map(one, range(200)))
    assert all(not e.created for e in engines), "refusal storm must create zero containers"


def test_between_phase_digest_drift_refused_and_phase1_destroyed(tmp_path: Path) -> None:
    def one(i: int):
        root = tmp_path / f"job{i}"
        root.mkdir()

        class DriftEngine(FakeEngine):
            calls = 0

            def inspect_digest(self, image: str) -> str:
                self.calls += 1
                return DIGEST if self.calls == 1 else DRIFTED

        engine = DriftEngine()
        with pytest.raises(provision.ProvisioningRefusal, match="digest_drift_between_phases"):
            provision.provision_in_sandbox(_repo(root), _plan(), engine, _wheelhouse(root))
        return engine

    with ThreadPoolExecutor(max_workers=16) as pool:
        engines = list(pool.map(one, range(50)))
    for e in engines:
        assert len(e.created) == 1, "phase-2 must never be created on drift"
        assert e.destroyed == ["ctr-1"], "phase-1 container must be destroyed on drift"


def test_400_parallel_integrity_records_and_single_bit_drift() -> None:
    def one(i: int):
        return integrity.build_integrity_record(
            source_bytes=b"print('hello')",
            image_digest=DIGEST,
            dependencies_text="demo==1.0",
            policy_text="network=none",
            command=["python", "-m", "pytest"],
            exit_code=0,
            output_bytes=b"1 passed",
        )

    with ThreadPoolExecutor(max_workers=32) as pool:
        records = list(pool.map(one, range(400)))
    digests = {r.digest() for r in records}
    assert len(digests) == 1, "canonical digests must agree across 400 parallel builds"

    base = records[0]
    flipped = integrity.build_integrity_record(
        source_bytes=b"print('hellp')",  # single-bit content drift
        image_digest=DIGEST,
        dependencies_text="demo==1.0",
        policy_text="network=none",
        command=["python", "-m", "pytest"],
        exit_code=0,
        output_bytes=b"1 passed",
    )
    verdict = integrity.compare_runs(base, flipped)
    assert verdict["reproducible"] is False
    assert "source_sha256" in verdict["differences"]


def test_100_parallel_output_guard_zero_false_accepts(tmp_path: Path) -> None:
    def one(i: int):
        root = tmp_path / f"out{i}"
        root.mkdir()
        (root / "ok.txt").write_bytes(b"evidence")
        (root / "evil.txt").symlink_to("/etc/passwd")
        scan = outputguard.scan_output_tree(root, limits=outputguard.OutputLimits())
        return scan

    with ThreadPoolExecutor(max_workers=32) as pool:
        scans = list(pool.map(one, range(100)))
    assert all(not s.ok for s in scans), "symlink must be refused every time"
    assert all(any("symlink" in v for v in s.violations) for s in scans)


def test_readiness_determinism_100x() -> None:
    text = "pytest==8.0.0\nrequests==2.32.3\n"
    lock = "pytest==8.0.0\nrequests==2.32.3\n"
    target = {"pytest", "requests"}
    results = set()
    last = None
    for _ in range(100):
        last = readiness.evaluate_readiness(text, target_runtime=target, lock_text=lock)
        payload = {
            "ok": last.ok,
            "problems": list(last.problems),
            "host_only": list(last.host_only),
        }
        results.add(json.dumps(payload, sort_keys=True))
    assert len(results) == 1, "readiness verdict must be deterministic at 100x"
    assert last is not None and last.ok is True
