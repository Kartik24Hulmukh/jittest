"""Two-phase sandbox provisioning (handoff P0-1).

Phase 1 (fetch): wheels are built/fetched inside a tightly scoped,
network-enabled container that is destroyed immediately afterwards.
Phase 2 (run): install and execution happen in a fresh network=none
container from the frozen wheelhouse manifest. There is no host
fallback: any engine, digest or policy failure refuses fail-closed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .verify import VerifyRefusalError

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
FORBIDDEN_REQ_RE = re.compile(
    r"(^|\s)(-e\s|--editable\s)|(git|hg|svn|bzr)\+|file://|^\s*\.|^\s*/",
    re.IGNORECASE,
)


class ProvisioningRefusal(VerifyRefusalError):
    """Fail-closed refusal for any provisioning policy violation."""


@dataclass(frozen=True)
class ArtifactPin:
    name: str
    version: str
    sha256: str
    filename: str


@dataclass(frozen=True)
class ProvisionManifest:
    image: str
    image_digest: str
    python: str
    requirements_hash: str
    artifacts: tuple
    network_policy: Literal["fetch", "none"]

    def to_dict(self) -> dict:
        return {
            "image": self.image,
            "image_digest": self.image_digest,
            "python": self.python,
            "requirements_hash": self.requirements_hash,
            "artifacts": [a.__dict__ for a in self.artifacts],
            "network_policy": self.network_policy,
        }


@dataclass(frozen=True)
class EngineAdapter:
    """Injectable container-engine seam (docker/podman in CI, fakes in tests).

    ``inspect_repo_digests`` is optional but authoritative: when the engine
    exposes it, provisioning requires the pinned digest to appear in the
    engine's RepoDigests array. A local image Id is never sufficient proof.
    """

    name: str
    inspect_digest: Callable[[str], str]
    create: Callable[[dict], str]
    destroy: Callable[[str], None]
    inspect_repo_digests: Callable[[str], Sequence[str]] | None = None


def validate_digest(digest: str) -> None:
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ProvisioningRefusal("image_digest_required: pinned sha256 digest is mandatory")


def hash_requirements(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_requirements(lines: Sequence[str]) -> None:
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if FORBIDDEN_REQ_RE.search(line):
            raise ProvisioningRefusal(
                "unapproved_dependency: editable/VCS/local-path requirement refused: " + line
            )


def freeze_wheelhouse(wheelhouse: Path) -> tuple:
    wheels = sorted(Path(wheelhouse).glob("*.whl"))
    if not wheels:
        raise ProvisioningRefusal("wheelhouse_empty: phase-1 produced no frozen artifacts")
    pins = []
    for wheel in wheels:
        parts = wheel.name.split("-")
        if len(parts) < 2:
            raise ProvisioningRefusal("wheelhouse_malformed: " + wheel.name)
        with wheel.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        pins.append(
            ArtifactPin(
                name=parts[0],
                version=parts[1],
                sha256=digest,
                filename=wheel.name,
            )
        )
    return tuple(pins)


def build_manifest(
    image: str,
    image_digest: str,
    python_version: str,
    requirements_text: str,
    artifacts: tuple,
    network_policy: Literal["fetch", "none"] = "fetch",
) -> ProvisionManifest:
    validate_digest(image_digest)
    return ProvisionManifest(
        image=image,
        image_digest=image_digest,
        python=python_version,
        requirements_hash=hash_requirements(requirements_text),
        artifacts=tuple(artifacts),
        network_policy=network_policy,
    )


@contextmanager
def _container(engine: EngineAdapter, spec: dict) -> Iterator[str]:
    """Own one acquired container; preserve a primary failure during cleanup.

    A failed destroy is not proof of release. Refuse progression, report it,
    and leave reconciliation to the engine/operator rather than retrying an
    operation whose outcome is unknown. Process-control exceptions propagate.
    """
    cid = engine.create(spec)
    primary: BaseException | None = None
    try:
        yield cid
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            engine.destroy(cid)
        except Exception as exc:
            message = "cleanup_failure_" + spec["phase"] + ": " + type(exc).__name__
            if primary is not None:
                primary.add_note(message)
            else:
                raise ProvisioningRefusal(message) from exc


def provision_in_sandbox(repo: Path, plan: Mapping, engine: EngineAdapter, wheelhouse: Path) -> ProvisionManifest:
    """Run the two-phase provisioning contract; never falls back to the host."""
    try:
        image = plan["image"]
        expected = plan["image_digest"]
        validate_digest(expected)
        python_version = plan.get("python", "3.12")
        requirements = plan.get("requirements", "requirements.txt")
        if not all(isinstance(value, str) and value for value in (image, python_version, requirements)):
            raise ProvisioningRefusal("invalid_plan: image, python and requirements must be nonempty strings")
        if engine.inspect_repo_digests is not None:
            repo_digests = list(engine.inspect_repo_digests(image))
            if not repo_digests:
                raise ProvisioningRefusal(
                    "missing_repo_digests: engine returned no authoritative RepoDigests"
                )
            if not any(d.partition("@")[2] == expected for d in repo_digests):
                raise ProvisioningRefusal("digest_mismatch: authoritative RepoDigests lack the pin")
        authoritative = engine.inspect_digest(image)
        if authoritative != expected:
            raise ProvisioningRefusal("digest_mismatch: authoritative RepoDigests differ from pin")
        req_path = Path(repo) / requirements
        req_text = req_path.read_text(encoding="utf-8")
        check_requirements(req_text.splitlines())
    except ProvisioningRefusal:
        raise
    except Exception as exc:
        raise ProvisioningRefusal("preflight_failure: " + type(exc).__name__) from exc
    try:
        with _container(engine, {"image": image, "digest": expected, "network": "fetch", "phase": "fetch"}):
            pins = freeze_wheelhouse(wheelhouse)
    except ProvisioningRefusal:
        raise
    except Exception as exc:  # engine failure: refuse, never retry unconfined
        raise ProvisioningRefusal("engine_failure_phase1: " + type(exc).__name__) from exc
    manifest = build_manifest(
        image, expected, python_version, req_text, pins, "none"
    )
    manifest_hash = hashlib.sha256(
        json.dumps(manifest.to_dict(), sort_keys=True).encode("utf-8")
    ).hexdigest()
    try:
        again = engine.inspect_digest(image)
        if again != expected:
            raise ProvisioningRefusal("digest_drift_between_phases")
        with _container(
            engine,
            {
                "image": image,
                "digest": expected,
                "network": "none",
                "read_only_rootfs": True,
                "no_new_privileges": True,
                "cap_drop": "ALL",
                "phase": "run",
                "manifest_hash": manifest_hash,
            },
        ):
            pass
    except ProvisioningRefusal:
        raise
    except Exception as exc:
        raise ProvisioningRefusal("engine_failure_phase2: " + type(exc).__name__) from exc
    return manifest
