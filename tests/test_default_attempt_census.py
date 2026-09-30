"""Actual harmless CLI/Action executions plus interruption/material regressions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from jittest.receipt import verify_receipt
from jittest.results import AttemptCensus
from jittest.verify import verify_test

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("census_consumer", ROOT / "scripts/check_distributable.py")
assert SPEC and SPEC.loader
CONSUMER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONSUMER)


def environment():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("JITTEST", "GITHUB", "GIT_", "PYTHON"))}
    env.update(PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1",
               GITHUB_EVENT_NAME="push")
    return env


def fixture(tmp_path):
    repo = tmp_path / "fixture"
    repo.mkdir()
    env = environment()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    git("init", "-q")
    git("config", "user.name", "Harmless Census Fixture")
    git("config", "user.email", "fixture@example.invalid")
    (repo / "calc.py").write_text("def double(x): return x * 2\n")
    (repo / "test_calc.py").write_text("from calc import double\ndef test_double(): assert double(2) == 4\n")
    (repo / "test_deleted.py").write_text("def test_old(): assert True\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "calc.py").write_text("def double(x): return x * 3\n")
    with (repo / "test_calc.py").open("a") as stream:
        stream.write("# changed candidate\n")
    (repo / "test_deleted.py").unlink()
    (repo / "test_invalid.py").write_bytes(b"\xff\n")
    git("add", "-A")
    git("commit", "-qm", "head")
    return repo, base, git("rev-parse", "HEAD")


def snapshots(output):
    return [(p, json.loads(p.read_text())) for p in output.glob("census/*/snapshot.json")]


def test_actual_cli_signed_census_and_export_hashes(tmp_path):
    repo, base, head = fixture(tmp_path)
    out = tmp_path / "receipt.json"
    run = subprocess.run([sys.executable, "-m", "jittest", "verify", "--repo", str(repo),
          "--base", base, "--head", head, "--test", "test_calc.py", "--timeout", "5",
          "--sandbox-mode", "off", "--output", str(out), "--json"], env=environment(),
          cwd=tmp_path, timeout=60, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    receipt = json.loads(out.read_text())
    assert verify_receipt(receipt).valid
    assert receipt["verdict"] == "proven_catch"
    census_path, census = snapshots(tmp_path)[0]
    assert receipt["attempt_census"] == census
    CONSUMER.assert_attempt_census(census, census_path.with_name("journal.jsonl"),
        expected_base=base, expected_head=head,
        expected_sources={"test_calc.py": hashlib.sha256((repo / "test_calc.py").read_bytes()).hexdigest()})
    assert census["candidates"][0]["execution_observed"]
    assert census["candidates"][0]["disposition"] == receipt["disposition"]
    changed = json.loads(json.dumps(receipt))
    changed["attempt_census"]["candidates"][0]["disposition"] = "not_the_observed_result"
    assert not verify_receipt(changed).valid


def test_actual_action_retains_deleted_refused_and_executed_candidates(tmp_path):
    repo, base, head = fixture(tmp_path)
    out = tmp_path / "action-evidence"
    env = environment()
    env.update(JITTEST_REPO_PATH=str(repo), JITTEST_BASE=base, JITTEST_HEAD=head,
               JITTEST_SANDBOX_MODE="off", JITTEST_POLICY="advisory", JITTEST_OUTPUT_DIR=str(out))
    run = subprocess.run([sys.executable, "-m", "jittest.action"], env=env, cwd=tmp_path,
                         timeout=60, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    census_path, census = next((p, d) for p, d in snapshots(out) if d["entrypoint"] == "action")
    candidates = {c["selector"]: c for c in census["candidates"]}
    assert set(candidates) == {"test_calc.py", "test_deleted.py", "test_invalid.py"}
    assert candidates["test_deleted.py"]["candidate_sha256"] is None
    assert candidates["test_deleted.py"]["disposition"] == "file_not_found"
    assert not candidates["test_deleted.py"]["execution_observed"]
    assert candidates["test_invalid.py"]["disposition"].startswith("refused_")
    assert candidates["test_invalid.py"]["candidate_sha256"] == hashlib.sha256(b"\xff\n").hexdigest()
    assert not candidates["test_invalid.py"]["execution_observed"]
    assert candidates["test_calc.py"]["disposition"] == "catching"
    assert candidates["test_calc.py"]["execution_observed"]
    CONSUMER.assert_attempt_census(census, census_path.with_name("journal.jsonl"),
        expected_base=base, expected_head=head,
        expected_sources={k: c["candidate_sha256"] for k, c in candidates.items()})
    journal = census_path.with_name("journal.jsonl").read_text()
    assert '"event":"verification_refused"' in journal
    assert all(c["state"] == "finished" for c in candidates.values())


def test_actual_cli_prepare_refusal_keeps_durable_unexecuted_census(tmp_path):
    repo, base, head = fixture(tmp_path)
    out = tmp_path / "refusal.json"
    run = subprocess.run([sys.executable, "-m", "jittest", "verify", "--repo", str(repo),
          "--base", base, "--head", head, "--test", "test_calc.py", "--path", "../escape",
          "--sandbox-mode", "off", "--output", str(out)], env=environment(),
          cwd=tmp_path, timeout=30, capture_output=True, text=True)
    assert run.returncode == 2
    assert not out.exists()  # existing prepare-refusal report contract
    _, census = snapshots(tmp_path)[0]
    candidate = census["candidates"][0]
    assert candidate["disposition"] == "refused_unsafe_execution_path"
    assert candidate["base_sha"] == base and candidate["head_sha"] == head
    assert not candidate["execution_observed"]
    assert census["state"] == "failed"


def test_interruption_retains_started_phase_without_inventing_outcome(tmp_path):
    repo, base, head = fixture(tmp_path)
    out = tmp_path / "interrupted.json"
    with mock.patch("jittest.verify.run_test", side_effect=KeyboardInterrupt), pytest.raises(KeyboardInterrupt):
        verify_test(repo, base, head, "test_calc.py", output_path=out, sandbox_mode="off")
    p, census = snapshots(tmp_path)[0]
    assert census["state"] == "interrupted"
    assert census["candidates"][0]["disposition"] == "interrupted"
    records = [json.loads(line) for line in p.with_name("journal.jsonl").read_text().splitlines()]
    assert any(r["event"] == "phase_started" for r in records)
    terminal = next(r for r in records if r["event"] == "candidate_finished")
    assert terminal["phases"] and "outcome" not in terminal["phases"][0]
    assert not out.exists()


def test_material_binding_and_invocation_directories_are_independent(tmp_path):
    first = AttemptCensus.candidate(selector="test.py", base="a" * 40, head="b" * 40,
                                    source=b"full candidate\n")
    changed = AttemptCensus.candidate(selector="test.py", base="a" * 40, head="c" * 40,
                                      source=b"full candidate\n")
    assert first["material_sha256"] != changed["material_sha256"]
    changed = AttemptCensus.candidate(selector="test.py", base="a" * 40, head="b" * 40,
                                      source=b"full candidate\n# trailing exact byte\n")
    assert first["material_sha256"] != changed["material_sha256"]
    a = AttemptCensus(tmp_path, entrypoint="verify")
    b = AttemptCensus(tmp_path, entrypoint="verify")
    assert a.directory != b.directory
    assert a.snapshot()["state"] == "started"  # no invented terminal event on lost process


def test_actual_action_does_not_reuse_stale_receipt_after_refusal_write_failure(tmp_path):
    from jittest.action import run_action
    repo, base, head = fixture(tmp_path)
    out = tmp_path / "reused-output"
    env = environment()
    env.update(JITTEST_BASE=base, JITTEST_HEAD=head)
    with mock.patch.dict(os.environ, env, clear=True):
        assert run_action(repo, sandbox_override="off", policy="advisory", output_dir=out) == 0
        stale = next(out.glob("evidence-test_calc-*.json"))
        assert json.loads(stale.read_text())["verdict"] == "proven_catch"
        (repo / "test_calc.py").write_bytes(b"\xff\n")
        with mock.patch("jittest.action.make_refusal_receipt", side_effect=OSError("injected export failure")):
            assert run_action(repo, sandbox_override="off", policy="advisory", output_dir=out) == 0
    census = next(d for _, d in snapshots(out) if d["entrypoint"] == "action"
                  and next(c for c in d["candidates"] if c["selector"] == "test_calc.py")["candidate_bytes"] == 2)
    candidate = next(c for c in census["candidates"] if c["selector"] == "test_calc.py")
    assert not candidate["execution_observed"], "old receipt phases must not count as current execution"
    assert candidate.get("artifact") is None
