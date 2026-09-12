"""Chaos-engineering resilience suite (2026-09-12 round 3).

The engine is detonated at every seam - create phase 1, create phase 2,
digest inspection, wheelhouse freeze, destroy - and adversarial
requirement vectors are fired at the gate. The invariant: the system
refuses honestly and never falls back to the host. A failed destroy
remains unresolved; it is not evidence of successful resource release.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

try:
    import pytest
except ModuleNotFoundError as exc:  # dependency-free unittest discovery
    import unittest

    raise unittest.SkipTest("requires pytest; exercised by the pytest CI lane") from exc

from jittest import provision

DIGEST = "sha256:" + "ab" * 32
NL = chr(10)


class ChaosEngine:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.created = []
        self.destroyed = []

    def inspect_digest(self, image):
        if self.fail_at == "inspect":
            raise ConnectionError("daemon unreachable")
        return DIGEST

    def inspect_repo_digests(self, image):
        return ["img@" + DIGEST]

    def create(self, spec):
        if self.fail_at == "create_" + spec["phase"]:
            raise RuntimeError("engine exploded")
        self.created.append(spec)
        return f"ctr-{len(self.created)}"

    def destroy(self, cid):
        if self.fail_at == "destroy":
            raise RuntimeError("destroy failed")
        self.destroyed.append(cid)


def _adapter(engine):
    return provision.EngineAdapter(
        name="chaos",
        inspect_digest=engine.inspect_digest,
        create=engine.create,
        destroy=engine.destroy,
        inspect_repo_digests=engine.inspect_repo_digests,
    )


def _setup(tmp, reqs="demo==1.0"):
    (tmp / "requirements.txt").write_text(reqs + NL, encoding="utf-8")
    wh = tmp / "wheelhouse"
    wh.mkdir()
    (wh / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel")
    return tmp, wh, {"image": "img", "image_digest": DIGEST, "python": "3.12"}


def test_engine_explosion_at_phase1_create_refuses(tmp_path):
    repo, wh, plan = _setup(tmp_path)
    engine = ChaosEngine(fail_at="create_fetch")
    with pytest.raises(provision.ProvisioningRefusal, match="engine_failure_phase1"):
        provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)
    assert engine.created == []


def test_engine_explosion_at_phase2_create_refuses_and_destroys_phase1(tmp_path):
    repo, wh, plan = _setup(tmp_path)
    engine = ChaosEngine(fail_at="create_run")
    with pytest.raises(provision.ProvisioningRefusal, match="engine_failure_phase2"):
        provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)
    assert len(engine.created) == 1
    assert engine.destroyed == ["ctr-1"], "phase-1 container must not leak"


def test_inspect_digest_connection_failure_refuses_no_host_fallback(tmp_path):
    repo, wh, plan = _setup(tmp_path)
    engine = ChaosEngine(fail_at="inspect")
    with pytest.raises(provision.ProvisioningRefusal):
        provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)
    assert engine.created == [], "no container may be created when digests cannot be verified"


def test_empty_wheelhouse_refused_before_phase2(tmp_path):
    (tmp_path / "requirements.txt").write_text("demo==1.0" + NL, encoding="utf-8")
    wh = tmp_path / "wheelhouse"
    wh.mkdir()
    plan = {"image": "img", "image_digest": DIGEST, "python": "3.12"}
    engine = ChaosEngine()
    with pytest.raises(provision.ProvisioningRefusal, match="wheelhouse_empty"):
        provision.provision_in_sandbox(tmp_path, plan, _adapter(engine), wh)
    assert all(c["phase"] == "fetch" for c in engine.created), "phase-2 must never start"


def test_destroy_failure_still_refuses_honestly(tmp_path):
    repo, wh, plan = _setup(tmp_path)
    engine = ChaosEngine(fail_at="destroy")
    with pytest.raises(provision.ProvisioningRefusal):  # never silent success
        provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)


@pytest.mark.parametrize(
    "evil",
    [
        "-e git+https://evil.example/repo.git#egg=demo",
        "git+https://evil.example/repo.git",
        "file:///etc/passwd",
        "./local/path",
        "-e .",
    ],
)
def test_adversarial_requirement_vectors_refused_pre_container(tmp_path, evil):
    repo, wh, plan = _setup(tmp_path, reqs=evil)
    engine = ChaosEngine()
    with pytest.raises(provision.ProvisioningRefusal, match="unapproved_dependency"):
        provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)
    assert engine.created == [], "adversarial requirement must be refused before any container"


def test_200_job_mixed_honest_evil_storm(tmp_path):
    def one(i):
        root = tmp_path / ("job" + str(i))
        root.mkdir()
        honest = i % 2 == 0
        reqs = "demo==1.0" if honest else "git+https://evil.example/r.git"
        repo, wh, plan = _setup(root, reqs=reqs)
        engine = ChaosEngine()
        try:
            provision.provision_in_sandbox(repo, plan, _adapter(engine), wh)
            return "accepted", honest
        except provision.ProvisioningRefusal:
            return "refused", honest

    with ThreadPoolExecutor(max_workers=32) as pool:
        outcomes = list(pool.map(one, range(200)))
    wrong = [(out, hon) for out, hon in outcomes if (out == "accepted") != hon]
    assert wrong == [], "100% correct decisions required, got " + str(wrong[:5])
