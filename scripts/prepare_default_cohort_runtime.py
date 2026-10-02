"""Prepare only the fixed, preregistered default-product cohort runtime.

Trusted package wheels only: no project checkout/Dockerfile/installer enters the
build context. Registry publication is ONLY to a job-owned loopback registry.
The existing verify_registry_live.py supplies verified official platform pins.
This helper neither executes a project nor implements a dependency resolver.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

MANIFEST_SHA256 = "152f191c55c4ff6570962e461c42f2413aa772ce9afc49912fb65916b284778a"
SELECTED_ROWS_SHA256 = "9d05340b0de871faa90a5c0c91b1589381ef1585d330c943199e6430130cdb00"
APPROVED_CONFIGS = {'click/07c909f23f0f83b5ca137c167b9a134d66201f67': '87bf078e2c9357d8121391441d97737332190d2fcbd608853f7b70347a94bd1e', 'click/445310365b3a0437d5e46bf57fa2a801b704c30d': '87bf078e2c9357d8121391441d97737332190d2fcbd608853f7b70347a94bd1e', 'click/7925a3410d7098c28cfca3b2baa6c852666bbd14': '87bf078e2c9357d8121391441d97737332190d2fcbd608853f7b70347a94bd1e', 'click/916883afad450c0c9bbc4212817900949131adbd': '70f8fe8664e5585add884175b80bf003c648037d89a2b23317d68faf172742e4', 'click/9f9b149ea30287b4977b800a024ee68144b8c869': '87bf078e2c9357d8121391441d97737332190d2fcbd608853f7b70347a94bd1e', 'click/bec59289d8cf9b9b4010642b2fee483e5f8eeefc': '70f8fe8664e5585add884175b80bf003c648037d89a2b23317d68faf172742e4', 'flask/1d49747264554dee31f5627d4249d09aaaeced39': 'ea0777ce44101efe5edd8c152aceef898acf9a98c8bd840ad98473611a573948', 'flask/689362089edd09b6d68f7cfe99075e1345e0fede': 'ea0777ce44101efe5edd8c152aceef898acf9a98c8bd840ad98473611a573948', 'flask/7b0088693ece1bd3a9238a6fdf56ed8df7a4d43b': 'd854ea9b22fb746cf92861cdd566fe598d64218ec75e11addc921a32fb4a6660', 'flask/d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9': 'd854ea9b22fb746cf92861cdd566fe598d64218ec75e11addc921a32fb4a6660', 'flask/e82db2ca3a22c9614c1987392c9cfaa8c6ce99ad': 'd854ea9b22fb746cf92861cdd566fe598d64218ec75e11addc921a32fb4a6660', 'flask/fbb6f0bc4c60a0bada0e03c3480d0ccf30a3c1df': 'd854ea9b22fb746cf92861cdd566fe598d64218ec75e11addc921a32fb4a6660', 'rich/19c67b9a3479841e9133bea94607c89ee931d3fc': '7988c916a401110bac2e684a24a9479f057a3ceff6ccf181c4ee66e9df51fa2d', 'rich/46cebbb032f920eb096efbaf23cdc6fe9dd541f7': '3762cb9e96442f57b8ff080f5ecd4d06ebdb8616e33d3a1eb2ba1974e58b7b65', 'rich/7ef2d05ca8aa3cb405dab2fdf3282e69cf8089e3': '7988c916a401110bac2e684a24a9479f057a3ceff6ccf181c4ee66e9df51fa2d', 'rich/b17c6169a4188d4a0ecb0153072a0061e62b8ec7': 'c1ed0f8b5c27801c1cfd9baf367fef11681a9689525b191dabe9e5734a9c4a89', 'rich/ce51a2f8bf326878a94a382cb7102c85824f7e04': '3762cb9e96442f57b8ff080f5ecd4d06ebdb8616e33d3a1eb2ba1974e58b7b65', 'rich/fc41075a3206d2a5fd846c6f41c4d2becab814fa': 'c1ed0f8b5c27801c1cfd9baf367fef11681a9689525b191dabe9e5734a9c4a89'}
# Manually approved from every selected BASE/HEAD pyproject. Flask/Rich
# themselves are NOT installed. Click is a declared Flask dependency; each
# project remains imported from its confined source checkout by the core.
# Rich's test constraint ^7 selects pytest 7 rather than the old GA73 pytest8.
PINS = (
    "pytest==7.4.4", "pytest-timeout==2.3.1", "packaging==24.2",
    "pluggy==1.5.0", "iniconfig==2.0.0", "blinker==1.9.0",
    "click==8.1.8", "itsdangerous==2.2.0", "Jinja2==3.1.6",
    "MarkupSafe==3.0.2", "Werkzeug==3.1.3", "asgiref==3.8.1",
    "greenlet==3.1.1", "python-dotenv==1.0.1", "markdown-it-py==3.0.0",
    "mdurl==0.1.2", "Pygments==2.19.1", "attrs==21.4.0",
    "typing-extensions==4.12.2", "pytest-cov==3.0.0", "coverage==7.6.12",
)
DOCKERFILE = """ARG PYTHON_BASE
FROM ${PYTHON_BASE}
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.lock /opt/default-cohort-requirements.lock
RUN python -m pip download --only-binary=:all: --no-deps --dest /opt/default-cohort-wheels -r /opt/default-cohort-requirements.lock \
    && python -m pip install --no-index --no-deps --find-links /opt/default-cohort-wheels -r /opt/default-cohort-requirements.lock \
    && python -m pip check
USER 65534:65534
WORKDIR /workspace
"""
INVENTORY = """import hashlib, importlib.metadata as m, json
from pathlib import Path
print(json.dumps({
 'packages': sorted([{'name': d.metadata['Name'], 'version': d.version} for d in m.distributions()], key=lambda d: d['name'].lower()),
 'wheels': [{'filename': p.name, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size} for p in sorted(Path('/opt/default-cohort-wheels').glob('*.whl'))]
}))
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def validate_material(manifest: Path, repos: Path, output: Path) -> dict:
    raw = manifest.read_bytes()
    if digest(raw) != MANIFEST_SHA256:
        raise ValueError("preregistered_manifest_changed")
    m = json.loads(raw)
    rows = m["rows"]
    if len(rows) != 9 or m["selected_rows_sha256"] != SELECTED_ROWS_SHA256:
        raise ValueError("selected_cohort_changed")
    if digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()) != SELECTED_ROWS_SHA256:
        raise ValueError("selected_cohort_hash_mismatch")
    evidence = output / "dependency-configs"
    evidence.mkdir()
    inventory = {}
    for row in rows:
        for side in ("base_sha", "head_sha"):
            project, sha = row["repo_name"], row[side]
            key = project + "/" + sha
            if key in inventory:
                continue
            if key not in APPROVED_CONFIGS:
                raise ValueError("unreviewed_dependency_config")
            env = {"PATH": os.environ["PATH"], "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"}
            result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C",
                str(repos / project), "show", sha + ":pyproject.toml"],
                env=env, capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError("selected_dependency_material_unavailable:" + key)
            data = result.stdout
            actual = digest(data)
            # This is a frozen allowlist, NOT evaluation of project packaging.
            # TOML is parsed as inert data, never imported or installed.
            parsed = tomllib.loads(data.decode())
            if actual != APPROVED_CONFIGS[key]:
                raise ValueError("reviewed_dependency_config_changed:" + key)
            path = evidence / (project + "-" + sha + "-pyproject.toml")
            path.write_bytes(data)
            inventory[key] = {"sha256": actual, "file": path.name,
                "project_dependencies": parsed.get("project", {}).get("dependencies", []),
                "test_group": parsed.get("dependency-groups", {}).get("tests", []),
                "poetry_dependencies": parsed.get("tool", {}).get("poetry", {}).get("dependencies", {}),
                "poetry_dev_dependencies": parsed.get("tool", {}).get("poetry", {}).get("dev-dependencies", {})}
    if set(inventory) != set(APPROVED_CONFIGS):
        raise ValueError("selected_dependency_review_incomplete")
    save(output / "dependency-review.json", inventory)
    return m


def verified_pin(path: Path, repo: str, tag: str) -> str:
    proof = json.loads(path.read_bytes())
    prefix = "docker.io/" + repo + "@sha256:"
    ref = proof.get("pinned_ref", "")
    if (proof.get("status") != "RUN" or proof.get("verified") is not True
            or proof.get("backend") != "docker" or proof.get("repo") != repo
            or proof.get("tag") != tag or proof.get("arch") != "amd64"
            or not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", ref)
            or proof.get("digest") != ref.partition("@")[2]):
        raise ValueError("official_registry_pin_unverified")
    return ref


def prepare(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    record = {"status": "NOT_RUN", "manifest_sha256": MANIFEST_SHA256,
              "registry_scope": "job_owned_loopback_only", "fixed_pins": list(PINS),
              "declared_generation_calls": 0, "ci_cost_authority": "not_measured"}
    save(output / "runtime-proof.json", record)
    owned = False
    try:
        validate_material(args.manifest, args.repo_root, output)
        base = verified_pin(args.base_proof, "library/python", "3.12-slim")
        registry = verified_pin(args.registry_proof, "library/registry", "2")
        record.update(base_image=base, registry_image=registry)
        if not re.fullmatch(r"default-cohort-registry-[0-9]+-[0-9]+", args.registry_name):
            raise ValueError("unsafe_owned_registry_name")
        if not re.fullmatch(r"[0-9]+-[0-9]+", args.owner):
            raise ValueError("unsafe_owner_id")
        # Blank Docker config and isolated CLI HOME: no runner credentials or
        # candidate bytes enter either Docker build context or mounts.
        with tempfile.TemporaryDirectory(prefix="default-cohort-runtime-") as temp:
            home = Path(temp) / "home"
            home.mkdir()
            env = {"PATH": os.environ["PATH"], "HOME": str(home),
                   "DOCKER_CONFIG": str(home / ".docker")}

            def run(argv: list[str], label: str, timeout: int = 120) -> bytes:
                save(output / (label + ".command.json"), argv)
                try:
                    result = subprocess.run(argv, env=env, capture_output=True, timeout=timeout)
                except subprocess.TimeoutExpired as exc:
                    (output / (label + ".stdout")).write_bytes(exc.stdout or b"")
                    (output / (label + ".stderr")).write_bytes(exc.stderr or b"")
                    save(output / (label + ".status.json"), {"timeout": True,
                        "timeout_seconds": timeout, "returncode": None})
                    raise RuntimeError("trusted_runtime_operation_timeout:" + label) from exc
                # No provider/key env is passed. Retained output belongs only
                # to trusted Docker operations with fixed public package pins.
                (output / (label + ".stdout")).write_bytes(result.stdout)
                (output / (label + ".stderr")).write_bytes(result.stderr)
                save(output / (label + ".status.json"), {"returncode": result.returncode})
                if result.returncode:
                    raise RuntimeError("trusted_runtime_operation_failed:" + label)
                return result.stdout

            def repo_proof(ref: str, label: str) -> dict:
                inspected = json.loads(run(["docker", "image", "inspect", ref], label))[0]
                refs = inspected.get("RepoDigests", [])
                if not any(r.partition("@")[2] == ref.partition("@")[2] for r in refs):
                    raise ValueError("authoritative_repo_digest_missing:" + label)
                proof = {"reference": ref, "RepoDigests": refs,
                         "local_image_id_non_authoritative": inspected.get("Id"),
                         "architecture": inspected.get("Architecture"),
                         "os": inspected.get("Os")}
                save(output / (label + ".json"), proof)
                return proof

            record["base_repo_proof"] = repo_proof(base, "base-inspect")
            record["registry_repo_proof"] = repo_proof(registry, "registry-inspect")
            context = output / "trusted-build-context"
            context.mkdir()
            lock = "\n".join(PINS) + "\n"
            (context / "Dockerfile").write_text(DOCKERFILE)
            (context / "requirements.lock").write_text(lock)
            record["recipe_sha256"] = digest(DOCKERFILE.encode())
            record["requirements_sha256"] = digest(lock.encode())
            local = "localhost:5000/jittest-default-cohort:" + args.owner
            run(["docker", "build", "--pull=false", "--build-arg", "PYTHON_BASE=" + base,
                 "--tag", local, str(context)], "runtime-build", 600)
            cid = run(["docker", "run", "--detach", "--name", args.registry_name,
                "--label", "jittest.default-cohort-owner=" + args.owner,
                "--publish", "127.0.0.1:5000:5000", registry], "registry-start").decode().strip()
            owned = True
            record["registry_container_id"] = cid
            # Only the owned loopback service readiness is polled, at most
            # twenty seconds. There is no candidate/dependency substitution.
            ready = False
            for _ in range(20):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:5000/v2/", timeout=1) as response:
                        ready = response.status == 200
                except OSError:
                    pass
                if ready:
                    break
                time.sleep(0.5)
            if not ready:
                raise RuntimeError("owned_loopback_registry_not_ready")
            run(["docker", "push", local], "loopback-push", 180)
            info = json.loads(run(["docker", "image", "inspect", local], "runtime-local-inspect"))[0]
            refs = [r for r in info.get("RepoDigests", [])
                    if re.fullmatch(r"localhost:5000/jittest-default-cohort@sha256:[0-9a-f]{64}", r)]
            if len(refs) != 1:
                raise ValueError("runtime_registry_repo_digest_missing")
            image = refs[0]
            run(["docker", "pull", image], "runtime-pull", 180)
            record["runtime_repo_proof"] = repo_proof(image, "runtime-pinned-inspect")
            prefix = ["docker", "run", "--rm", "--label",
                "jittest.default-cohort-owner=" + args.owner, "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "64", "--memory", "256m", "--cpus", "1",
                "--user", "65534:65534", "--entrypoint", "python", image]
            inventory = json.loads(run(prefix + ["-I", "-s", "-B", "-c", INVENTORY], "inventory"))
            def normalize(s: str) -> str:
                return re.sub(r"[-_.]+", "-", s).lower()
            actual = {normalize(p["name"]): p["version"] for p in inventory["packages"]}
            for pin in PINS:
                name, version = pin.split("==")
                if actual.get(normalize(name)) != version:
                    raise ValueError("fixed_dependency_inventory_mismatch:" + name)
            if len(inventory["wheels"]) != len(PINS):
                raise ValueError("fixed_wheel_inventory_incomplete")
            save(output / "wheel-inventory.json", inventory)
            run(prefix + ["-I", "-m", "pip", "freeze", "--all"], "pip-freeze")
            run(prefix + ["-I", "-m", "pip", "check"], "pip-check")
            record.update(status="RUN", runtime_image=image, verified_repo_digest=image.partition("@")[2])
    except Exception as exc:
        record.update(status="NOT_RUN", error_type=type(exc).__name__, reason=str(exc))
        raise
    finally:
        if owned:
            # An independent always() workflow cleanup also reconciles the label
            # if this process/job was interrupted before reaching this block.
            try:
                result = subprocess.run(["docker", "rm", "--force", args.registry_name],
                    env={"PATH": os.environ["PATH"], "HOME": "/nonexistent",
                         "DOCKER_CONFIG": "/nonexistent"}, capture_output=True, timeout=60)
                record["registry_cleanup_returncode"] = result.returncode
                (output / "registry-cleanup.stdout").write_bytes(result.stdout)
                (output / "registry-cleanup.stderr").write_bytes(result.stderr)
                if result.returncode:
                    record["status"] = "NOT_RUN"
            except (OSError, subprocess.TimeoutExpired) as exc:
                record.update(status="NOT_RUN", registry_cleanup_returncode=None,
                              registry_cleanup_error=type(exc).__name__)
        save(output / "runtime-proof.json", record)
    if record["status"] != "RUN":
        raise RuntimeError("runtime_registry_cleanup_failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-proof", type=Path, required=True)
    parser.add_argument("--registry-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry-name", required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    try:
        prepare(args)
    except Exception as exc:
        # Never print credential-bearing Docker/installer diagnostics to logs.
        print("default cohort runtime preparation refused: " + type(exc).__name__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
