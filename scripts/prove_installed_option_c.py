"""Real-daemon installed-wheel BASE-image proof; NOT_RUN always fails closed.

Executes only the harness's harmless synthetic fixture, never a corpus or PR's
Dockerfile. The supplied image must be an authoritative registry digest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
import venv
from pathlib import Path

PUBLIC_SIGNER = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
FIXTURE_ORIGIN = "github.com/jittest-fixtures/installed-option-c"


def prove(wheel: Path, image: str, record: dict) -> None:
    if not shutil.which("docker"):
        raise RuntimeError("docker unavailable")
    if "@sha256:" not in image:
        raise ValueError("authoritative digest-pinned image required")
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTHON", "JITTEST", "GITHUB", "GIT_"))
           and k not in {"MELIOUS_API_KEY", "GH_TOKEN"}}
    env.update(JITTEST_SANDBOX_BACKEND="docker")

    def run(args, *, cwd=None, expected=0, timeout=120):
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=timeout)
        if result.returncode != expected:
            raise RuntimeError(f"expected exit {expected}, got {result.returncode}: "
                               f"{result.stderr[-600:]}")
        return result.stdout.strip()

    # Authoritative verification occurs on this job's real daemon, not another
    # runner's cached claim. Pulling is preparation, not candidate networking.
    run(["docker", "pull", image], timeout=300)
    record["containers_before"] = run(["docker", "ps", "-q"]).split()
    with tempfile.TemporaryDirectory(prefix="jt-installed-option-c-") as temp:
        root = Path(temp)
        env["HOME"] = str(root / "home")
        Path(env["HOME"]).mkdir()
        venv.EnvBuilder(with_pip=True).create(root / "venv")
        python = root / "venv/bin/python"
        run([str(python), "-m", "pip", "install", "--no-index", "--no-deps",
             str(wheel.resolve())], cwd=root)
        verified = json.loads(run([str(python), "-c",
            "import json,sys; from jittest.registry import verify_image_digest; "
            "print(json.dumps(verify_image_digest('docker', sys.argv[1])))", image], cwd=root))
        if not verified[0]:
            raise RuntimeError("this daemon did not verify authoritative RepoDigests")
        pip_version = run(["docker", "run", "--rm", "--network", "none",
                           "--entrypoint", "python", image, "-c",
                           "import importlib.metadata; print(importlib.metadata.version('pip'))"])
        repo = root / "fixture"
        repo.mkdir()

        def git(*args):
            return run(["git", "-C", str(repo), *args])

        git("init", "-q")
        git("config", "user.name", "Jittest Public Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "commit.gpgsign", "false")
        git("remote", "add", "origin", "https://" + FIXTURE_ORIGIN + ".git")
        key = root / "PUBLIC_TEST_ONLY.seed"
        key.write_bytes(bytes(range(32)))
        key.chmod(0o600)
        sentinel = root / ("host-sentinel-" + uuid.uuid4().hex)
        sentinel.write_text("PUBLIC_SYNTHETIC_SENTINEL")
        env["JT_OPTION_C_SECRET"] = "PUBLIC_SYNTHETIC_ENV_SENTINEL"
        test = repo / "test_calc.py"
        test.write_text(
            "import os, socket\nfrom pathlib import Path\n"
            "from calc import double\n"
            "def test_double():\n"
            "    import pip\n"
            "    assert pip.__version__\n"
            "    assert os.getenv('JT_OPTION_C_SECRET') is None\n"
            f"    assert not Path({str(sentinel)!r}).exists()\n"
            f"    assert not Path({str(key)!r}).exists()\n"
            "    try:\n"
            "        connection = socket.create_connection(('1.1.1.1', 443), timeout=0.5)\n"
            "    except OSError:\n"
            "        pass\n"
            "    else:\n"
            "        connection.close()\n"
            "        raise AssertionError('candidate network was not denied')\n"
            "    assert double(2) == 4\n"
        )
        config = ('[project]\nname="harmless-fixture"\nversion="0.0.0"\n'
                  f'dependencies=["pip=={pip_version}"]\n'
                  '[tool.jittest.runtime]\n'
                  f'image="{image}"\n')
        (repo / "pyproject.toml").write_text(config)
        (repo / "calc.py").write_text("def double(x):\n    return x * 2\n")
        git("add", ".")
        git("commit", "-qm", "trusted BASE")
        base = git("rev-parse", "HEAD")
        (repo / "calc.py").write_text("def double(x):\n    return x * 3\n")
        (repo / "pyproject.toml").write_text(config.replace(
            image, "example.invalid/hostile@sha256:" + "f" * 64))
        git("add", ".")
        git("commit", "-qm", "head regression and hostile image override")
        head = git("rev-parse", "HEAD")
        cli = [str(python), "-m", "jittest"]
        common = ["--repo", str(repo), "--base", base, "--head", head,
                  "--test", "test_calc.py", "--sandbox-mode", "required",
                  "--signing-key", str(key), "--reruns", "2"]
        checks = ["--expected-signer", PUBLIC_SIGNER, "--strict-signer",
                  "--expected-base", base, "--expected-head", head,
                  "--expected-repo", FIXTURE_ORIGIN, "--require-confined", "--json"]
        full_test = test.read_text()
        test.write_text(full_test.replace("    assert double(2) == 4\n", "    assert True\n"))
        canaries = root / "canaries.json"
        run(cli + ["verify", *common, "--timeout", "15", "--output", str(canaries), "--json"],
            cwd=root, expected=1, timeout=180)
        canary_receipt = json.loads(canaries.read_text())
        if (canary_receipt["verdict"] != "non_discriminating"
                or any(canary_receipt[side]["outcome"] != "PASS"
                       for side in ("base_execution", "head_execution"))):
            raise RuntimeError("isolation canaries did not pass on both revisions")
        run(cli + ["verify-receipt", str(canaries), *checks,
                   "--expected-test-sha256", hashlib.sha256(test.read_bytes()).hexdigest()],
            cwd=root)
        record["canary_receipt"] = canary_receipt
        test.write_text(full_test)
        artifact = root / "receipt.json"
        run(cli + ["verify", *common, "--timeout", "15", "--output", str(artifact), "--json"],
            cwd=root, timeout=180)
        receipt = json.loads(artifact.read_text())
        if receipt["verdict"] != "proven_catch" or receipt["sandbox"]["image"] != image:
            raise RuntimeError("required BASE image catch not established")
        if receipt["signature"]["verifying_key"] != PUBLIC_SIGNER:
            raise RuntimeError("producer did not use externally known fixture signer")
        check = checks + ["--expected-test-sha256", hashlib.sha256(test.read_bytes()).hexdigest()]
        consumer = json.loads(run(cli + ["verify-receipt", str(artifact), *check], cwd=root))
        record.update(status="RUN", verified_digest=verified[2], pip_version=pip_version,
                      base_sha=base, head_sha=head, receipt=receipt, consumer=consumer,
                      host_key_environment_network_canaries_passed=True,
                      head_image_override_ignored=True)
        # Verify a real timeout/descendant case from the same installed wheel.
        test.write_text("import subprocess,sys,time\n"
                        "def test_timeout():\n"
                        "    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                        "    time.sleep(60)\n")
        timed = root / "timeout.json"
        run(cli + ["verify", *common, "--timeout", "5", "--output", str(timed), "--json"],
            cwd=root, expected=1, timeout=60)
        timeout_receipt = json.loads(timed.read_text())
        if (timeout_receipt["verdict"] != "inconclusive" or timeout_receipt["proven_catch"]
                or timeout_receipt["head_execution"]["outcome"] != "TIMEOUT"):
            raise RuntimeError("timeout became a proven catch")
        timeout_check = check.copy()
        timeout_check[timeout_check.index("--expected-test-sha256") + 1] = (
            hashlib.sha256(test.read_bytes()).hexdigest())
        run(cli + ["verify-receipt", str(timed), *timeout_check], cwd=root)
        record["timeout_receipt"] = timeout_receipt
    record["containers_after"] = run(["docker", "ps", "-q"]).split()
    if set(record["containers_after"]) - set(record["containers_before"]):
        raise RuntimeError("new running containers survived timeout teardown")
    record["timeout_cleanup_passed"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    record = {"status": "NOT_RUN", "image": args.image,
              "wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
              "qualification_scope": "installed_wheel_dependency_bearing_public_required_path",
              "fixture_only_not_universal_safety": True}
    started = time.monotonic()
    try:
        prove(args.wheel, args.image, record)
        record["passed"] = True
    except Exception as exc:
        record.update(passed=False, error_type=type(exc).__name__, error=str(exc))
    record["seconds"] = time.monotonic() - started
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in record.items()
                      if k not in {"receipt", "consumer", "timeout_receipt", "canary_receipt"}}, indent=2))
    return 0 if record["passed"] and record["status"] == "RUN" else 1


if __name__ == "__main__":
    raise SystemExit(main())