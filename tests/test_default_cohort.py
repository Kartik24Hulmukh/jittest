"""Owned safe fixtures only: never execute third-party project code on host."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import SkipTest
from unittest.mock import patch

try:
    import pytest
except ModuleNotFoundError as exc:
    if exc.name != "pytest":
        raise
    raise SkipTest("Prospective fixture suite requires optional pytest; run with dev test dependencies") from exc

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("default_cohort", ROOT / "scripts/run_default_cohort.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def fixture_repo(root):
    repo = root / "owned"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "--template=", str(repo)], check=True)
    def git(*args):
        env = harness.clean_git_env()
        env.update(GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
                   GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env).decode().strip()
    (repo / "tests").mkdir()
    source = b"# frozen LF bytes\ndef test_owned():\n    assert True\n"
    (repo / "tests/test_owned.py").write_bytes(source)
    git("add", ".")
    tree = git("write-tree")
    base = git("commit-tree", tree, "-m", "owned base")
    (repo / "owned.txt").write_text("fixture change\n")
    git("add", ".")
    head = git("commit-tree", git("write-tree"), "-p", base, "-m", "owned head")
    git("update-ref", "refs/heads/main", head)
    git("symbolic-ref", "HEAD", "refs/heads/main")
    # Poison checkout, including CRLF/filter settings: never use these bytes.
    (repo / "tests/test_owned.py").write_bytes(b"raise RuntimeError('outer checkout poison')\r\n")
    git("config", "core.autocrlf", "true")
    row = {"row_id": "owned_01", "kind": "bug", "repository": "https://github.com/fixture/owned",
           "repo_name": "owned", "test": "tests/test_owned.py", "base_sha": base, "head_sha": head}
    return repo, row, source


def manifest(tmp, rows):
    frame = [{k: v for k, v in row.items() if k != "test_source_ref"} for row in rows]
    body = {"cohort_name": "owned_safe_fixture", "sampling_frame": frame,
            "sampling_frame_sha256": harness.sha256(harness.canonical(frame)),
            "rows": rows, "selected_rows_sha256": harness.sha256(harness.canonical(rows))}
    path = tmp / "manifest.json"
    harness.save_json(path, body)
    return path


def test_real_preregistration_matches_original_frame():
    body, _ = harness.load_manifest(ROOT / "eval/default_product_cohort.json")
    raw = (ROOT / "eval/layer1b_manifest.json").read_bytes()
    assert body["sampling_frame_source_sha256"] == harness.sha256(raw)
    assert body["sampling_frame"] == json.loads(raw)["rows"]
    assert len(body["rows"]) == 9
    assert {r["repo_name"] for r in body["rows"]} == {"flask", "click", "rich"}
    for project in ("flask", "click", "rich"):
        expected = []
        for kind, size in (("bug", 2), ("control", 1)):
            expected += [r["row_id"] for r in body["sampling_frame"]
                         if r["repo_name"] == project and r["kind"] == kind][:size]
        assert [r["row_id"] for r in body["rows"] if r["repo_name"] == project] == expected
    assert body["human_labels"] is None and body["recall"] is None and body["false_positive_rate"] is None


def test_frozen_blob_and_bundle_survive_poisoned_checkout(tmp_path):
    repo, row, source = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    out = tmp_path / "evidence"
    out.mkdir()
    stage = tmp_path / "stage"
    pins = harness.freeze(row, repo, stage, out)
    assert (out / "candidate.py").read_bytes() == source
    assert (stage / row["test"]).read_bytes() == source
    assert pins["test_file_sha256"] == harness.sha256(source)
    clone = tmp_path / "independent"
    subprocess.run(["git", "clone", "-q", "--bare", str(out / "source.bundle"), str(clone)], check=True)
    recovered = subprocess.check_output(["git", "-C", str(clone), "show",
                                        row["test_source_ref"] + ":" + row["test"]])
    assert recovered == source


def test_actual_public_cli_absent_backend_refuses_and_retains_census(tmp_path):
    _, row, source = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [row])
    env = {"JITTEST_SANDBOX_BACKEND": "none", "PYTHONPATH": str(ROOT / "src")}
    with patch.dict(os.environ, env):
        result = harness.run_cohort(path, tmp_path, tmp_path / "out")
    outcome = result["rows"][0]
    out = tmp_path / "out" / row["row_id"]
    assert outcome["cli_exit_code"] == 2
    assert outcome["status"] == "receipt_or_refusal_retained"
    receipt = json.loads((out / "receipt.json").read_bytes())
    assert receipt["refusal"]["code"] == "sandbox_unavailable"
    assert receipt["sandbox"]["backend"] == "none"
    assert outcome["receipt_check_exit_code"] == 0
    assert outcome["confinement_check_exit_code"] == 7
    assert list((out / "census").rglob("*.json"))
    argv = json.loads((out / "verify.command.json").read_bytes())
    assert argv[:4] == [sys.executable, "-m", "jittest", "verify"]
    assert argv[argv.index("--sandbox-mode") + 1] == "required"
    assert "--no-sandbox" not in argv and "--allow-unconfined" not in argv
    assert (out / "candidate.py").read_bytes() == source
    assert result["human_labels"] is None and result["provider_cost_usd"] is None
    inventory = json.loads((tmp_path / "out/artifact_inventory.json").read_bytes())
    for file, digest in inventory.items():
        assert harness.sha256((tmp_path / "out" / file).read_bytes()) == digest
    assert not list((tmp_path / "out").rglob("*.pem"))
    expected = json.loads((tmp_path / "out/expected_signer.json").read_bytes())["verifying_key"]
    for label in ("receipt_check", "confinement_check"):
        consumer = json.loads((out / (label + ".command.json")).read_bytes())
        assert consumer[consumer.index("--expected-signer") + 1] == expected
        assert "--strict-signer" in consumer
        payload = json.loads((out / (label + ".stdout")).read_bytes())
        assert payload["signer_status"] == "TRUSTED"
        consumer[consumer.index("--expected-signer") + 1] = "00" * 32
        wrong = subprocess.run(consumer, capture_output=True, env=dict(os.environ, **env))
        assert wrong.returncode == 3
        assert json.loads(wrong.stdout)["signer_status"] == "UNTRUSTED"
    key_path = Path(argv[argv.index("--signing-key") + 1])
    candidate_repo = Path(argv[argv.index("--repo") + 1])
    assert not key_path.is_relative_to(candidate_repo)
    assert not key_path.is_relative_to(tmp_path / "out")
    assert not key_path.exists()  # Fresh key destroyed after invocation.
    keygen_cmd = json.loads((tmp_path / "out/signing_identity.command.json").read_bytes())
    assert keygen_cmd[-1] == str(key_path)


def test_all_unavailable_rows_retained_and_outputs_single_use(tmp_path):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    rows = [dict(row, row_id=f"missing_{n}", repo_name="unavailable") for n in range(3)]
    path = manifest(tmp_path, rows)
    out = tmp_path / "out"
    result = harness.run_cohort(path, tmp_path, out)
    assert len(result["rows"]) == 3
    assert all(r["status"] == "error_retained" for r in result["rows"])
    assert all((out / r["row_id"] / "error.json").exists() for r in rows)
    with pytest.raises(FileExistsError):
        harness.run_cohort(path, tmp_path, out)


@pytest.mark.parametrize("field,value", [("row_id", "../escape"), ("test", "../escape.py"),
                                        ("base_sha", "HEAD"), ("test_source_ref", "HEAD"),
                                        ("repo_name", "../escape")])
def test_bad_declarations_rejected_before_output(tmp_path, field, value):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    row[field] = value
    path = manifest(tmp_path, [row])
    with pytest.raises(ValueError):
        harness.run_cohort(path, tmp_path, tmp_path / "never")
    assert not (tmp_path / "never").exists()


def test_manifest_tampering_rejected(tmp_path):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [row])
    body = json.loads(path.read_bytes())
    body["rows"][0]["test"] = "other.py"
    harness.save_json(path, body)
    with pytest.raises(ValueError, match="selected rows hash mismatch"):
        harness.load_manifest(path)


def test_timeout_outputs_retained(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        harness.command([sys.executable, "-c", "import time; print('started',flush=True); time.sleep(5)"],
                        tmp_path, "timeout", timeout=0.1)
    assert (tmp_path / "timeout.stdout").is_file()
    assert (tmp_path / "timeout.stderr").is_file()
    assert json.loads((tmp_path / "timeout.status.json").read_bytes())["timeout"] is True


def test_symlink_blob_rejected_without_execution(tmp_path):
    repo, row, _ = fixture_repo(tmp_path)
    env = harness.clean_git_env()
    env.update(GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="fixture@example.invalid",
               GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="fixture@example.invalid")
    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], env=env).decode().strip()
    blob = subprocess.check_output(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                                   input=b"../owned.txt", env=env).decode().strip()
    git("update-index", "--add", "--cacheinfo", f"120000,{blob},{row['test']}")
    row["base_sha"] = git("commit-tree", git("write-tree"), "-m", "symlink fixture")
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [row])
    result = harness.run_cohort(path, tmp_path, tmp_path / "out")
    assert result["rows"][0]["status"] == "error_retained"
    assert "regular Git blob" in result["rows"][0]["error"]
    assert not (tmp_path / "out" / row["row_id"] / "verify.command.json").exists()


def test_duplicate_rows_rejected_before_output(tmp_path):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [row, row])
    with pytest.raises(ValueError, match="duplicate row_id"):
        harness.run_cohort(path, tmp_path, tmp_path / "never")
    assert not (tmp_path / "never").exists()


def test_unavailable_interpreter_keeps_all_cli_launch_errors(tmp_path):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [dict(row, row_id=f"owned_{n}") for n in range(2)])
    result = harness.run_cohort(path, tmp_path, tmp_path / "out", python="/nonexistent/python")
    assert len(result["rows"]) == 2
    assert all(r["error_type"] == "FileNotFoundError" for r in result["rows"])
    assert (tmp_path / "out/signing_identity.status.json").exists()
    assert all((tmp_path / "out" / r["row_id"] / "pins.json").exists()
               for r in result["rows"])
    assert all(not (tmp_path / "out" / r["row_id"] / "verify.command.json").exists()
               for r in result["rows"])


@pytest.mark.skipif(os.name != "posix", reason="owned POSIX CLI signal/PID regression")
def test_timeout_actual_cli_runs_interrupt_cleanup_for_separate_candidate_session(tmp_path):
    """Only owned code runs unconfined; production run_cohort still requires isolation."""
    import contextlib
    import signal

    repo, row, _ = fixture_repo(tmp_path)
    marker = tmp_path / "candidate_pids.json"
    test = repo / row["test"]
    test.write_text(
        "import json,os,subprocess,sys,time\nfrom pathlib import Path\n"
        "def test_owned():\n"
        "    child = subprocess.Popen([sys.executable, '-S', '-c', 'import time; time.sleep(60)'])\n"
        f"    Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
        "    time.sleep(60)\n")
    out = tmp_path / "cli_probe"
    out.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    env = {k: os.environ[k] for k in ("PATH",) if k in os.environ}
    env.update(HOME=str(tmp_path), TMPDIR=str(scratch), PYTHONPATH=str(ROOT / "src"),
               PYTHONDONTWRITEBYTECODE="1", JITTEST_FORCE_MINIRUNNER="1", PIP_NO_INDEX="1", UV_OFFLINE="1")
    # Normalize inherited background-shell SIGINT disposition only in this probe.
    bootstrap = ("import runpy,signal; signal.signal(signal.SIGINT, signal.default_int_handler); "
                 "runpy.run_module('jittest', run_name='__main__')")
    argv = [sys.executable, "-S", "-c", bootstrap, "verify", "--repo", str(repo),
            "--base", row["base_sha"], "--head", row["head_sha"], "--test", row["test"],
            "--sandbox-mode", "off", "--timeout", "60", "--output", str(out / "receipt.json")]
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            harness.command(argv, out, "actual_cli", env=env, timeout=5)
        assert marker.exists(), "owned candidate must actually begin execution"
        candidate_pids = json.loads(marker.read_text())
        for pid in candidate_pids:
            state = subprocess.run(["ps", "-p", str(pid), "-o", "stat="],
                                   capture_output=True, text=True, timeout=2).stdout.strip()
            assert not state or state.startswith("Z"), f"owned PID {pid} still running: {state}"
        status = json.loads((out / "actual_cli.status.json").read_bytes())
        assert status["cleanup_grace_completed"] is True
        assert status["cleanup_forced"] is False
        assert status["cli_returncode"] == 130
        assert b"jittest: interrupted" in (out / "actual_cli.stderr").read_bytes()
        assert not (out / "receipt.json").exists()
        snapshots = list((out / "census").rglob("snapshot.json"))
        assert len(snapshots) == 1
        assert json.loads(snapshots[0].read_bytes())["state"] == "interrupted"
        assert subprocess.check_output(["git", "-C", str(repo), "worktree", "list", "--porcelain"]).count(b"worktree ") == 1
    finally:
        if marker.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(json.loads(marker.read_text())[0], signal.SIGKILL)



@pytest.mark.skipif(os.name != "posix", reason="owned POSIX detached-process boundary regression")
def test_timeout_detached_pipe_holder_is_bounded_and_cleanup_unknown(tmp_path):
    import contextlib
    import signal
    import time

    marker = tmp_path / "detached.json"
    code = (
        "import json,os,signal,subprocess,sys,time; from pathlib import Path; "
        "signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "child=subprocess.Popen([sys.executable,'-S','-c','import time; time.sleep(60)'],start_new_session=True); "
        f"Path({str(marker)!r}).write_text(json.dumps(child.pid)); "
        "print('detached-owned-child',flush=True); time.sleep(60)"
    )
    started = time.monotonic()
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            harness.command([sys.executable, "-S", "-c", code], tmp_path, "detached",
                            timeout=1, cleanup_grace_s=.2)
        assert marker.exists(), "owned detached process must actually start"
        status = json.loads((tmp_path / "detached.status.json").read_bytes())
        assert status["cleanup_forced"] is True
        assert status["cleanup_grace_completed"] is False
        assert status["output_drain_completed"] is False
        assert status["cleanup_scope"] == "forced_outer_process_group_only"
        assert status["descendant_cleanup"].startswith("unknown")
        assert time.monotonic() - started < 12
        assert b"detached-owned-child" in (tmp_path / "detached.stdout").read_bytes()
    finally:
        if marker.exists():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(json.loads(marker.read_text()), signal.SIGKILL)



def test_cli_subprocess_allowlist_removes_fake_secrets_and_proxies(tmp_path):
    _, row, _ = fixture_repo(tmp_path)
    row["test_source_ref"] = row["base_sha"]
    path = manifest(tmp_path, [row])
    sensitive = {"OPENAI_API_KEY": "owned-fake-api-secret", "ANTHROPIC_API_KEY": "owned-fake-key",
                 "GITHUB_TOKEN": "owned-fake-token", "CUSTOM_SECRET": "owned-fake-secret",
                 "PASSWORD": "owned-fake-password", "AUTH_HEADER": "owned-fake-auth",
                 "OPENAI_BASE_URL": "https://example.invalid", "HTTPS_PROXY": "https://example.invalid"}
    env = dict(sensitive, JITTEST_SANDBOX_BACKEND="none", PYTHONPATH=str(ROOT / "src"))
    original = harness.command
    observed = {}
    def recording_command(argv, directory, label, **kwargs):
        if label in ("signing_identity", "verify", "receipt_check", "confinement_check"):
            child_env = kwargs["env"]
            assert not (set(sensitive) & set(child_env))
            assert child_env["JITTEST_SANDBOX_BACKEND"] == "none"
            observed[label] = sorted(child_env)
        return original(argv, directory, label, **kwargs)
    with patch.dict(os.environ, env), patch.object(harness, "command", side_effect=recording_command):
        result = harness.run_cohort(path, tmp_path, tmp_path / "out")
    assert set(observed) == {"signing_identity", "verify", "receipt_check", "confinement_check"}
    assert result["rows"][0]["cli_exit_code"] == 2
    request = json.loads((tmp_path / "out/runtime_request.json").read_bytes())
    assert request["environment_variable_names"] == observed["verify"]
    assert "owned-fake-api-secret" not in (tmp_path / "out/runtime_request.json").read_text()
