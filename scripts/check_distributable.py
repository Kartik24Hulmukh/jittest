"""Reconcile packaged source bytes and rehearse the exact wheel without publishing."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import tomllib
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reconcile(wheel: Path, root: Path = ROOT) -> dict[str, str]:
    """No missing, changed or unexpected Python package files are accepted."""
    source = {
        "jittest/" + p.relative_to(root / "src/jittest").as_posix(): p.read_bytes()
        for p in (root / "src/jittest").rglob("*.py")
    }
    with zipfile.ZipFile(wheel) as archive:
        packaged = {n: archive.read(n) for n in archive.namelist()
                    if n.startswith("jittest/") and n.endswith(".py")}
    if source != packaged:
        raise ValueError("wheel package bytes do not match source")
    return {n: hashlib.sha256(b).hexdigest() for n, b in sorted(source.items())}


def reconcile_sdist(sdist: Path, wheel: Path) -> dict:
    """Require sdist package bytes and runtime build identity to match the wheel."""
    with zipfile.ZipFile(wheel) as archive:
        packaged = {n: archive.read(n) for n in archive.namelist()
                    if n.startswith("jittest/") and
                    (n.endswith(".py") or n == "jittest/_build_provenance.json")}
        provenance = json.loads(packaged["jittest/_build_provenance.json"])
    with tarfile.open(sdist) as archive:
        sources = {}
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if len(parts) >= 4 and parts[1:3] == ("src", "jittest") and member.isfile():
                name = "/".join(parts[2:])
                if name.endswith(".py") or name == "jittest/_build_provenance.json":
                    if name in sources:
                        raise ValueError("duplicate source archive member")
                    sources[name] = archive.extractfile(member).read()
    if sources != packaged:
        raise ValueError("sdist package bytes or build identity differ from wheel")
    return provenance


def rehearse_receipts(python: Path, work: Path, env: dict) -> dict:
    """Only our own harmless fixture executes on host; not a confinement proof."""
    repo = work / "fixture"
    repo.mkdir()

    def command(args, expected=0, cwd=work):
        result = subprocess.run(args, cwd=cwd, env=env, timeout=60,
                                capture_output=True, text=True)
        if result.returncode != expected:
            raise ValueError(f"rehearsal expected exit {expected}, got {result.returncode}: "
                             f"{result.stderr[-500:]}")
        return result.stdout.strip()

    def git(*args):
        return command(["git", *args], cwd=repo)
    git("init", "-q")
    git("config", "user.name", "Jittest Harmless Release Fixture")
    git("config", "user.email", "fixture@example.invalid")
    # Inert origin identity only: no clone, fetch, push or credentials.
    git("remote", "add", "origin", "https://github.com/jittest-fixtures/harmless-release.git")
    (repo / "calc.py").write_text("def double(x):\n    return x * 2\n")
    test = repo / "test_calc.py"
    test.write_text("from calc import double\n\ndef test_double():\n    assert double(2) == 4\n")
    git("add", ".")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (repo / "calc.py").write_text("def double(x):\n    return x * 3\n")
    git("add", ".")
    git("commit", "-qm", "head")
    head = git("rev-parse", "HEAD")
    # Public deterministic fixture key only; never used for production trust.
    key = work / "PUBLIC_TEST_ONLY.seed"
    key.write_bytes(bytes(range(32)))
    key.chmod(0o600)
    receipt = work / "receipt.json"
    cli = [str(python), "-m", "jittest"]
    command(cli + ["verify", "--repo", str(repo), "--base", base, "--head", head,
                   "--test", "test_calc.py", "--reruns", "2", "--timeout", "5",
                   "--sandbox-mode", "off", "--signing-key", str(key),
                   "--output", str(receipt), "--json"])
    data = json.loads(receipt.read_text())
    if data["verdict"] != "proven_catch":
        raise ValueError("installed verifier failed harmless assertion regression")
    signer = "03a107bff3ce10be1d70dd18e74bc09967e4d6309ba50d5f1ddc8664125531b8"
    if data["signature"]["verifying_key"] != signer:
        raise ValueError("producer signer differs from externally fixed test key")
    checks = ["--expected-signer", signer, "--strict-signer", "--expected-base", base,
              "--expected-head", head, "--expected-test-sha256",
              hashlib.sha256(test.read_bytes()).hexdigest(),
              "--expected-repo", "github.com/jittest-fixtures/harmless-release"]
    command(cli + ["verify-receipt", str(receipt), *checks])
    command(cli + ["verify-receipt", str(receipt), *checks, "--require-confined"], 7)
    bad_head = checks.copy()
    bad_head[bad_head.index("--expected-head") + 1] = "f" * 40
    command(cli + ["verify-receipt", str(receipt), *bad_head], 6)
    bad_signer = checks.copy()
    bad_signer[bad_signer.index("--expected-signer") + 1] = "f" * 64
    command(cli + ["verify-receipt", str(receipt), *bad_signer], 3)
    data["wall_clock_s"] = 99999
    tampered = work / "tampered.json"
    tampered.write_text(json.dumps(data))
    command(cli + ["verify-receipt", str(tampered), *checks], 2)
    return {"fresh_assertion_roundtrip": True, "tamper_wrong_signer_wrong_head_rejected": True,
            "unconfined_claim_rejected_when_required": True,
            "qualification_scope": "own_harmless_host_fixture_not_confined_execution"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--out", type=Path, default=Path("candidate-manifest.json"))
    args = parser.parse_args()
    wheels = list(args.dist.glob("*.whl"))
    sdists = list(args.dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        parser.error("dist must contain exactly one wheel and one sdist")
    wheel = wheels[0].resolve()
    source_files = reconcile(wheel)
    provenance = reconcile_sdist(sdists[0], wheel)
    source_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    diff_hash = hashlib.sha256(subprocess.check_output(["git", "diff", "HEAD"], cwd=ROOT)).hexdigest()
    if provenance != {"source_sha": source_sha, "working_diff_sha256": diff_hash}:
        raise ValueError("packaged source identity differs from current build source")
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("PYTHON", "JITTEST", "GITHUB", "GIT_")) and k not in
           {"MELIOUS_API_KEY", "GITHUB_TOKEN", "GIT_AUTH_TOKEN"}}
    with tempfile.TemporaryDirectory(prefix="jittest-wheel-") as temp:
        work = Path(temp)
        venv.EnvBuilder(with_pip=True).create(work / "venv")
        python = work / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
                       cwd=work, env=env, check=True, timeout=120, capture_output=True)
        # Running outside checkout with no PYTHONPATH ensures installed bytes,
        # not an editable source tree, supply both commands.
        for command in (["--version"], ["verify", "--help"], ["verify-receipt", "--help"]):
            result = subprocess.run([str(python), "-m", "jittest", *command],
                                    cwd=work, env=env, check=True, timeout=30,
                                    capture_output=True, text=True)
            if command == ["--version"] and version not in result.stdout:
                raise ValueError("installed version mismatch")
        probe = subprocess.run(
            [str(python), "-c", "import jittest; print(jittest.__file__)"],
            cwd=work, env=env, check=True, timeout=30, capture_output=True, text=True)
        if str(work / "venv") not in probe.stdout:
            raise ValueError("source checkout shadowed installed wheel")
        receipt_rehearsal = rehearse_receipts(python, work, env)
    manifest = {
        "qualification_scope": "exact_package_bytes_clean_install_receipt_contract_not_confined_e2e",
        "version": version,
        "source_sha": source_sha,
        "working_diff_sha256": diff_hash,
        "packaged_build_provenance": provenance,
        "receipt_rehearsal": receipt_rehearsal,
        "source_files": source_files,
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in [wheel, sdists[0]]},
        "clean_install_smoke": True,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "source_files"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())