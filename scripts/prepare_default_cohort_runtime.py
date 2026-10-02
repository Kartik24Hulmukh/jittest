"""Prepare only the fixed, preregistered default-product cohort runtime.

Trusted package wheels only: no project checkout/Dockerfile/installer enters the
build context. Registry publication is ONLY to a job-owned loopback registry.
The existing verify_registry_live.py supplies verified official platform pins.
Preparation mode executes no project and implements no dependency resolver.
--diagnostic runs bounded confined installed APIs on the hosted runner only;
its supplemental output never replaces the original cohort outcomes.
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

# Original hosted artifact36998550280: immutable comparison data, not a claim
# that a newly built registry image is byte-identical or the same runtime.
ORIGINAL_BASE_IMAGE = 'docker.io/library/python@sha256:6b1f85a08c199d29d5b6d71ab9c27bd5b3b393492e01216a15758ff69c4be8b8'
ORIGINAL_RUNTIME_IMAGE = 'localhost:5000/jittest-default-cohort@sha256:d13b7766e1f97836e35dfdf0d56512287f6a29118d1187f3031146795b1070a8'
ORIGINAL_INVENTORY = {'packages': [{'name': 'asgiref', 'version': '3.8.1'}, {'name': 'attrs', 'version': '21.4.0'}, {'name': 'blinker', 'version': '1.9.0'}, {'name': 'click', 'version': '8.1.8'}, {'name': 'coverage', 'version': '7.6.12'}, {'name': 'greenlet', 'version': '3.1.1'}, {'name': 'iniconfig', 'version': '2.0.0'}, {'name': 'itsdangerous', 'version': '2.2.0'}, {'name': 'Jinja2', 'version': '3.1.6'}, {'name': 'markdown-it-py', 'version': '3.0.0'}, {'name': 'MarkupSafe', 'version': '3.0.2'}, {'name': 'mdurl', 'version': '0.1.2'}, {'name': 'packaging', 'version': '24.2'}, {'name': 'pip', 'version': '25.0.1'}, {'name': 'pluggy', 'version': '1.5.0'}, {'name': 'Pygments', 'version': '2.19.1'}, {'name': 'pytest', 'version': '7.4.4'}, {'name': 'pytest-cov', 'version': '3.0.0'}, {'name': 'pytest-timeout', 'version': '2.3.1'}, {'name': 'python-dotenv', 'version': '1.0.1'}, {'name': 'typing_extensions', 'version': '4.12.2'}, {'name': 'Werkzeug', 'version': '3.1.3'}], 'wheels': [{'bytes': 23118, 'filename': 'MarkupSafe-3.0.2-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl', 'sha256': 'e17c96c14e19278594aa4841ec148115f9c7615a47382ecb6b82bd8fea3ab0c8'}, {'bytes': 23828, 'filename': 'asgiref-3.8.1-py3-none-any.whl', 'sha256': '3e1e3ecc849832fe52ccf2cb6686b7a55f82bb1d6aee72a58826471390335e47'}, {'bytes': 60567, 'filename': 'attrs-21.4.0-py2.py3-none-any.whl', 'sha256': '2d27e3784d7a565d36ab851fe94887c5eccd6a463168875832a1be79c82828b4'}, {'bytes': 8458, 'filename': 'blinker-1.9.0-py3-none-any.whl', 'sha256': 'ba0efaa9080b619ff2f3459d1d500c57bddea4a6b424b60a91141db6fd2f08bc'}, {'bytes': 98188, 'filename': 'click-8.1.8-py3-none-any.whl', 'sha256': '63c132bbbed01578a06712a2d1f497bb62d9c1c0d329b7903a866228027263b2'}, {'bytes': 242142, 'filename': 'coverage-7.6.12-cp312-cp312-manylinux_2_5_x86_64.manylinux1_x86_64.manylinux_2_17_x86_64.manylinux2014_x86_64.whl', 'sha256': 'bda1c5f347550c359f841d6614fb8ca42ae5cb0b74d39f8a1e204815ebe25750'}, {'bytes': 613077, 'filename': 'greenlet-3.1.1-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl', 'sha256': '1443279c19fca463fc33e65ef2a935a5b09bb90f978beab37729e1c3c6c25fe9'}, {'bytes': 5892, 'filename': 'iniconfig-2.0.0-py3-none-any.whl', 'sha256': 'b6a85871a79d2e3b22d2d1b94ac2824226a63c6b741c88f7ae975f18b6778374'}, {'bytes': 16234, 'filename': 'itsdangerous-2.2.0-py3-none-any.whl', 'sha256': 'c6242fc49e35958c8b15141343aa660db5fc54d4f13a1db01a3f5891b98700ef'}, {'bytes': 134899, 'filename': 'jinja2-3.1.6-py3-none-any.whl', 'sha256': '85ece4451f492d0c13c5dd7c13a64681a86afae63a5f347908daf103ce6d2f67'}, {'bytes': 87528, 'filename': 'markdown_it_py-3.0.0-py3-none-any.whl', 'sha256': '355216845c60bd96232cd8d8c40e8f9765cc86f46880e43a8fd22dc1a1a8cab1'}, {'bytes': 9979, 'filename': 'mdurl-0.1.2-py3-none-any.whl', 'sha256': '84008a41e51615a49fc9966191ff91509e3c40b939176e643fd50a5c2196b8f8'}, {'bytes': 65451, 'filename': 'packaging-24.2-py3-none-any.whl', 'sha256': '09abb1bccd265c01f4a3aa3f7a7db064b36514d2cba19a2f694fe6150451a759'}, {'bytes': 20556, 'filename': 'pluggy-1.5.0-py3-none-any.whl', 'sha256': '44e1ad92c8ca002de6377e165f3e0f1be63266ab4d554740532335b9d75ea669'}, {'bytes': 1225293, 'filename': 'pygments-2.19.1-py3-none-any.whl', 'sha256': '9ea1544ad55cecf4b8242fab6dd35a93bbce657034b0611ee383099054ab6d8c'}, {'bytes': 325287, 'filename': 'pytest-7.4.4-py3-none-any.whl', 'sha256': 'b090cdf5ed60bf4c45261be03239c2c1c22df034fbffe691abe93cd80cea01d8'}, {'bytes': 20981, 'filename': 'pytest_cov-3.0.0-py3-none-any.whl', 'sha256': '578d5d15ac4a25e5f961c938b85a05b09fdaae9deef3bb6de9a6e766622ca7a6'}, {'bytes': 14148, 'filename': 'pytest_timeout-2.3.1-py3-none-any.whl', 'sha256': '68188cb703edfc6a18fad98dc25a3c61e9f24d644b0b70f33af545219fc7813e'}, {'bytes': 19863, 'filename': 'python_dotenv-1.0.1-py3-none-any.whl', 'sha256': 'f7b63ef50f1b690dddf550d03497b66d609393b40b564ed0d674909a68ebf16a'}, {'bytes': 37438, 'filename': 'typing_extensions-4.12.2-py3-none-any.whl', 'sha256': '04e5ca0351e0f3f85c6853954072df659d0d13fac324d0072316b67d7794700d'}, {'bytes': 224498, 'filename': 'werkzeug-3.1.3-py3-none-any.whl', 'sha256': '54b78bf3716d19a65be4fceccc0d1d7b89e608834989dfae50ea87564639213e'}]}
DIAGNOSTIC_ROWS = ("bug_flask_01", "bug_flask_02", "ctrl_flask_01", "bug_rich_22")
ORIGINAL_CANDIDATE_SHA256 = {'bug_flask_01': '43b4a6355ab16fd5c98a7d188eca102ee427928a2bed158782cb557dfdec37cc', 'bug_flask_02': '5e5338781123ba745e36c598b151d04eba785e694d34c451c490e4f626768de2', 'ctrl_flask_01': 'bf3b18ff51cc2891255f7efb70d320c0d034de51edcb9667d0f56494e9de2fd6', 'bug_rich_22': 'f72773293d8d00fd2f5994fe83e1046e075d64ee47de155e16f7279da9093dc9'}


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


def diagnose(args: argparse.Namespace) -> None:
    """Supplemental confined API replay, never a replacement cohort verdict."""
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    contexts = [{"row_id": row, "phase": phase, "status": "selected_not_attempted"}
                for row in DIAGNOSTIC_ROWS for phase in ("base", "head", "head_rerun_2")]
    record = {"status": "NOT_RUN", "scope": "supplemental_guarded_API_diagnostics_only",
        "original_hosted_run": 36998550280, "replacement_outcomes": False,
        "signed_receipt": False, "manifest_sha256": MANIFEST_SHA256,
        "original_base_image": ORIGINAL_BASE_IMAGE, "original_runtime_image": ORIGINAL_RUNTIME_IMAGE,
        "original_inventory": ORIGINAL_INVENTORY, "phases": contexts,
        "stream_encoding": "UTF-8 with replacement from RunResult strings; not undecoded OS bytes",
        "declared_generation_calls": 0}
    save(output / "diagnostic-census.json", record)
    primary = args.runtime_proof.parent.parent / "cohort/census.json"
    primary_before = digest(primary.read_bytes()) if primary.exists() else None
    record["primary_census_before_sha256"] = primary_before
    save(output / "diagnostic-census.json", record)
    # Drop runner credentials/proxies/provider variables before any trusted API
    # subprocess can execute. No credentials are put in mounts or raw logs.
    allowed = {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL",
        "JITTEST_RUNTIME_IMAGE", "JITTEST_SANDBOX_BACKEND", "JITTEST_FORCE_MINIRUNNER",
        "JITTEST_READINESS", "JITTEST_OUTPUT_GUARD"}
    clean = {k: v for k, v in os.environ.items() if k in allowed}
    clean.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    os.environ.clear()
    os.environ.update(clean)
    baseline = None

    def daemon_inventory(label: str) -> list[dict]:
        result = subprocess.run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"],
                                capture_output=True, timeout=30)
        (output / (label + ".jsonl")).write_bytes(result.stdout)
        save(output / (label + ".status.json"), {"returncode": result.returncode})
        if result.returncode:
            raise RuntimeError("diagnostic_daemon_inventory_failed")
        return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]

    try:
        manifest = validate_material(args.manifest, args.repo_root, output)
        (output / "preregistered_manifest.json").write_bytes(args.manifest.read_bytes())
        runtime = json.loads(args.runtime_proof.read_bytes())
        current = json.loads((args.runtime_proof.parent / "wheel-inventory.json").read_bytes())
        def canonical(x: object) -> bytes:
            return json.dumps(x, sort_keys=True, separators=(",", ":")).encode()
        comparison = {"original_base_image": ORIGINAL_BASE_IMAGE,
            "current_base_image": runtime.get("base_image"),
            "base_pin_equal": runtime.get("base_image") == ORIGINAL_BASE_IMAGE,
            "original_runtime_image": ORIGINAL_RUNTIME_IMAGE,
            "actual_new_runtime_image": runtime.get("runtime_image"),
            "runtime_pin_equal": runtime.get("runtime_image") == ORIGINAL_RUNTIME_IMAGE,
            "runtime_identity_reuse_claim": False,
            "original_inventory_sha256": digest(canonical(ORIGINAL_INVENTORY)),
            "current_inventory_sha256": digest(canonical(current)),
            "package_and_wheel_inventory_equal": current == ORIGINAL_INVENTORY}
        save(output / "runtime-comparison.json", comparison)
        record["runtime_comparison"] = comparison
        if runtime.get("status") != "RUN" or not comparison["base_pin_equal"] or not comparison["package_and_wheel_inventory_equal"]:
            raise ValueError("original_runtime_conditions_not_reproduced_no_diagnostic_execution")
        image = runtime["runtime_image"]
        if os.environ.get("JITTEST_RUNTIME_IMAGE") != image:
            raise ValueError("diagnostic_operator_runtime_mismatch")
        # Imports are ONLY trusted installed Jittest, never a public project.
        import sys

        import jittest
        package = Path(jittest.__file__).resolve()
        if not package.is_relative_to(Path(sys.prefix).resolve()):
            raise ValueError("diagnostic_requires_installed_wheel_not_checkout")
        from jittest.env import provision_environment
        from jittest.execute import Worktree
        from jittest.registry import verify_image_digest
        from jittest.sandbox import plan
        from jittest.verify import _run_guarded_phase
        record["installed_tool"] = {"python": sys.executable, "package_file": str(package),
            "build_provenance": json.loads((package.parent / "_build_provenance.json").read_bytes()),
            "wheel_byte_identity_claim": False}
        ok, _reason, verified = verify_image_digest("docker", image)
        if not ok or verified != image.partition("@")[2]:
            raise ValueError("diagnostic_authoritative_repo_digest_unverified")
        baseline = daemon_inventory("containers-before")
        sbx = plan("required", preferred="docker", runtime_image=image)
        if sbx.backend != "docker" or sbx.mode != "required" or not sbx.isolated or not sbx.network_denied:
            raise ValueError("diagnostic_required_docker_boundary_unavailable")
        record["sandbox_plan"] = sbx.as_dict()
        save(output / "diagnostic-census.json", record)
        selected = {row["row_id"]: row for row in manifest["rows"]}
        for row_id in DIAGNOSTIC_ROWS:
            row = selected[row_id]
            repo = (args.repo_root / row["repo_name"]).resolve()
            # Regular Git blob custody, not checkout filter/smudge execution.
            result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo),
                "ls-tree", "-z", row["test_source_ref"], "--", row["test"]],
                capture_output=True, timeout=60)
            entry = result.stdout
            if result.returncode or not entry.startswith((b"100644 blob ", b"100755 blob ")) or entry.count(b"\0") != 1:
                raise ValueError("diagnostic_candidate_not_regular_git_blob")
            blob = entry.split(b" ", 2)[2].split(b"\t", 1)[0].decode()
            result = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", blob],
                                    capture_output=True, timeout=60)
            if result.returncode:
                raise ValueError("diagnostic_candidate_blob_unavailable")
            candidate = result.stdout
            if digest(candidate) != ORIGINAL_CANDIDATE_SHA256[row_id]:
                raise ValueError("original_diagnostic_candidate_digest_changed")
            code = candidate.decode("utf-8")
            row_dir = output / row_id
            row_dir.mkdir()
            (row_dir / "candidate.py").write_bytes(candidate)
            save(row_dir / "pins.json", {**row, "test_git_blob": blob,
                "candidate_sha256": digest(candidate),
                "original_candidate_sha256": ORIGINAL_CANDIDATE_SHA256[row_id],
                "original_candidate_digest_equal": True, "source": "immutable_original_Git_blob"})
            # Public verify creates a fresh Worktree/provisioning per phase,
            # including HEAD rerun; never reuse candidate-mutated HEAD state.
            for side, phase_name in (("base", "base"), ("head", "head"), ("head", "head_rerun_2")):
                pending = [x for x in contexts if x["row_id"] == row_id and x["phase"] == phase_name]
                records = []
                try:
                    with Worktree(repo, row[side + "_sha"]) as workdir:
                        env = provision_environment(workdir, row[side + "_sha"], repo, sbx_plan=sbx)
                        if env.get("provisioning") != "option_c_trusted_image":
                            raise ValueError("diagnostic_non_image_provisioning_refused")
                        for phase_context in pending:
                            phase = phase_context["phase"]
                            phase_dir = row_dir / phase
                            phase_dir.mkdir()
                            phase_context.update(status="attempt_started", revision=row[side + "_sha"],
                                candidate_sha256=digest(candidate), test_path=row["test"],
                                backend=sbx.backend, runtime_image=image, workdir=str(workdir))
                            save(output / "diagnostic-census.json", record)
                            try:
                                result = _run_guarded_phase(workdir, code, phase=phase,
                                    revision=row[side + "_sha"], env_info=env, records=records,
                                    timeout_s=60, sbx=sbx, python_path=env.get("python_path"),
                                    rel_test_path=row["test"], node_id=None)
                                stdout = result.stdout.encode("utf-8", "replace")
                                stderr = result.stderr.encode("utf-8", "replace")
                                (phase_dir / "stdout").write_bytes(stdout)
                                (phase_dir / "stderr").write_bytes(stderr)
                                phase_context.update(status="RunResult_retained", outcome=result.outcome.name,
                                    failure_kind=result.failure_kind.value, exit_code=result.returncode,
                                    stdout_sha256=digest(stdout), stderr_sha256=digest(stderr),
                                    stdout_bytes=len(stdout), stderr_bytes=len(stderr))
                            except Exception as exc:
                                phase_context.update(status="phase_exception_retained",
                                    error_type=type(exc).__name__, error=str(exc))
                            finally:
                                save(phase_dir / "phase-context.json", phase_context)
                                save(phase_dir / "guarded-records.json", records)
                                save(output / "diagnostic-census.json", record)
                except Exception as exc:
                    for phase_context in pending:
                        if phase_context["status"] == "selected_not_attempted":
                            phase_context.update(status="setup_or_cleanup_exception_retained",
                                error_type=type(exc).__name__, error=str(exc))
                    save(row_dir / (phase_name + "-lifecycle-exception.json"),
                         {"error_type": type(exc).__name__, "error": str(exc)})
                    save(output / "diagnostic-census.json", record)
        record["status"] = "DIAGNOSTICS_RETAINED_NOT_COHORT_REPLACEMENT"
    except Exception as exc:
        record.update(status="DIAGNOSTIC_REFUSED", error_type=type(exc).__name__, error=str(exc))
        raise
    finally:
        if baseline is not None:
            try:
                after = daemon_inventory("containers-after-before-workflow-reconciliation")
                new = sorted(x["ID"] for x in after if x["ID"] not in {x["ID"] for x in baseline})
                record["cleanup_observation"] = {"new_surviving_container_ids": new,
                    "scope": "Docker inventory only; workflow always performs scoped final reconciliation",
                    "host_descendant_cleanup_claim": False}
            except Exception as exc:
                record["cleanup_observation"] = {"error_type": type(exc).__name__, "qualified": False}
        primary_after = digest(primary.read_bytes()) if primary.exists() else None
        record["primary_census_after_sha256"] = primary_after
        record["primary_census_unchanged"] = primary_before == primary_after
        save(output / "diagnostic-census.json", record)
        save(output / "artifact-inventory.json", {p.relative_to(output).as_posix(): digest(p.read_bytes())
            for p in sorted(output.rglob("*")) if p.is_file()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-proof", type=Path, required=True)
    parser.add_argument("--registry-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry-name", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--runtime-proof", type=Path)
    args = parser.parse_args()
    try:
        if args.diagnostic:
            if args.runtime_proof is None:
                raise ValueError("diagnostic_runtime_proof_required")
            diagnose(args)
        else:
            prepare(args)
    except Exception as exc:
        # Never print credential-bearing Docker/installer diagnostics to logs.
        print("default cohort runtime preparation refused: " + type(exc).__name__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
